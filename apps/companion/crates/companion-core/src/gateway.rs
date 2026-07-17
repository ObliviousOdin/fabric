//! The slice of the Fabric backend's `/api/ws` JSON-RPC protocol the
//! companion consumes, and the mapping from wire events onto
//! [`ActivitySignals`].
//!
//! The backend the Electron desktop app talks to is the FastAPI server from
//! `fabric_cli/web_server.py`, which mounts the `tui_gateway` JSON-RPC
//! dispatcher at `ws://127.0.0.1:<port>/api/ws`. Frames are single JSON
//! objects: requests `{jsonrpc, id, method, params}`, responses
//! `{jsonrpc, id, result|error}`, and server-pushed events
//! `{jsonrpc, method: "event", params: {type, session_id?, payload?}}`.
//! The server emits a `gateway.ready` event immediately after accept.
//!
//! Local auth is a query-string session token
//! (`?token=<FABRIC_DASHBOARD_SESSION_TOKEN>`): pin one via that env var when
//! spawning your own backend, or scrape `window.__FABRIC_SESSION_TOKEN__`
//! from `GET /` of a running `fabric dashboard`. Gated remote deployments use
//! single-use `?ticket=` credentials instead (30 s TTL — mint right before
//! every connect).
//!
//! The event → activity wiring below is a faithful port of the Electron
//! desktop's (`apps/desktop/src/app/session/hooks/use-message-stream/`
//! `gateway-event.ts` + `apps/desktop/src/store/pet.ts`), including its beat
//! timings and its "steady flags only count mid-turn" rule.

use serde::Deserialize;
use serde_json::Value as JsonValue;
use std::collections::HashSet;

use crate::state::ActivitySignals;

/// One parsed incoming WebSocket frame.
#[derive(Debug, Clone, PartialEq)]
pub enum Incoming {
    /// Server-pushed event: `{"method": "event", "params": {...}}`.
    Event(Event),
    /// Response to a request we sent: `{"id": ..., "result": ...}`.
    Response {
        id: JsonValue,
        result: Option<JsonValue>,
        error: Option<JsonValue>,
    },
}

/// A server-pushed event. `session_id` may be empty for global events.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Event {
    #[serde(rename = "type")]
    pub event_type: String,
    #[serde(default)]
    pub session_id: String,
    #[serde(default)]
    pub payload: JsonValue,
}

/// Parse one text frame. Returns None for frames the companion has no use
/// for (notifications other than `event`, malformed JSON) — the protocol is
/// forward-compatible and unknown traffic must never be an error.
pub fn parse_frame(text: &str) -> Option<Incoming> {
    let frame: JsonValue = serde_json::from_str(text).ok()?;
    if frame.get("method").and_then(JsonValue::as_str) == Some("event") {
        let event: Event = serde_json::from_value(frame.get("params")?.clone()).ok()?;
        return Some(Incoming::Event(event));
    }
    if let Some(id) = frame.get("id") {
        if !id.is_null() && (frame.get("result").is_some() || frame.get("error").is_some()) {
            return Some(Incoming::Response {
                id: id.clone(),
                result: frame.get("result").cloned(),
                error: frame.get("error").cloned(),
            });
        }
    }
    None
}

/// Serialize a JSON-RPC request frame.
pub fn request_frame(id: u64, method: &str, params: JsonValue) -> String {
    serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "method": method,
        "params": params,
    })
    .to_string()
}

/// Completion-beat duration: JUMP for ~2 loops of the 1100 ms animation.
pub const CELEBRATE_FLASH_MS: u64 = 2200;
/// Failure-beat duration (the desktop's `flashPetActivity` default).
pub const ERROR_FLASH_MS: u64 = 1600;
/// Greeting-beat duration (companion-native: WAVE when the session binds;
/// the CLI/TUI surfaces use WAVE for "turn finished cleanly / greeting", the
/// desktop never sets it — the overlay uses it only as a hello).
pub const GREET_FLASH_MS: u64 = 2200;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Flash {
    Celebrate,
    Error,
    Greet,
}

/// Folds gateway events into [`ActivitySignals`] with the desktop's exact
/// semantics:
///
/// - `reasoning.delta` / `reasoning.available` / `moa.reference` /
///   `moa.aggregating` → reasoning on.
/// - `tool.start` / `tool.progress` / `tool.generating` → tool running
///   (and reasoning off).
/// - `tool.complete` → tool running off.
/// - `message.start` → busy (turn in flight).
/// - `message.complete` → busy off, steady flags off, celebrate beat for
///   [`CELEBRATE_FLASH_MS`].
/// - `error` → busy off, steady flags off, error beat for [`ERROR_FLASH_MS`].
/// - `clarify.request` / `approval.request` / `sudo.request` /
///   `secret.request` → awaiting input until the matching respond is sent
///   (or the turn ends).
///
/// Beats share a single timer: a new flash replaces the previous one, and
/// only one of celebrate/error/greet shows at a time — so a clean finish can
/// never render the failed pose from a stale error. Steady flags
/// (tool running / reasoning) only count while a turn is live, so an
/// interrupted turn can't pin RUN/REVIEW.
///
/// Time is an injected `now_ms` monotonic milliseconds value so hosts
/// (Bevy's `Time`, tests) control the clock.
#[derive(Debug, Default)]
pub struct ActivityTracker {
    busy: bool,
    reasoning: bool,
    tool_running: bool,
    open_requests: HashSet<String>,
    flash: Option<(Flash, u64)>,
}

impl ActivityTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Companion-native greeting beat (session bound / pet appeared).
    pub fn greet(&mut self, now_ms: u64) {
        self.flash = Some((Flash::Greet, now_ms + GREET_FLASH_MS));
    }

    /// Seed the in-flight flag from a `session.resume` result's `running`
    /// field, so binding to a mid-turn session shows RUN immediately instead
    /// of idling until the next `message.start`.
    pub fn seed_running(&mut self, running: bool) {
        self.busy = running;
    }

    /// Record that we answered (or abandoned) an interactive request.
    pub fn resolve_request(&mut self, request_id: &str) {
        self.open_requests.remove(request_id);
    }

    /// Fold one server event in. Events for other sessions must be filtered
    /// out by the caller (the companion binds a single session per socket).
    pub fn apply(&mut self, event: &Event, now_ms: u64) {
        match event.event_type.as_str() {
            "message.start" => {
                self.busy = true;
            }
            "reasoning.delta" | "reasoning.available" | "moa.reference" | "moa.aggregating" => {
                self.reasoning = true;
            }
            "tool.start" | "tool.progress" | "tool.generating" => {
                self.reasoning = false;
                self.tool_running = true;
            }
            "tool.complete" => {
                self.tool_running = false;
                // Desktop parity: the first tool.complete after a blocking
                // prompt is that prompt resolving (answered on another
                // surface, or timed out server-side — clarify prompts
                // self-resolve after 300 s). Without this, a request answered
                // out-of-band would pin WAITING for the rest of the turn.
                self.open_requests.clear();
            }
            "message.complete" => {
                self.busy = false;
                self.reasoning = false;
                self.tool_running = false;
                self.open_requests.clear();
                self.flash = Some((Flash::Celebrate, now_ms + CELEBRATE_FLASH_MS));
            }
            "error" => {
                self.busy = false;
                self.reasoning = false;
                self.tool_running = false;
                self.open_requests.clear();
                self.flash = Some((Flash::Error, now_ms + ERROR_FLASH_MS));
            }
            "clarify.request" | "sudo.request" | "secret.request" => {
                // These are routed through the server's `_block()` seam,
                // which injects a request_id into the payload.
                if let Some(id) = event.payload.get("request_id").and_then(JsonValue::as_str) {
                    self.open_requests.insert(id.to_owned());
                }
            }
            "approval.request" => {
                // Approval prompts carry NO request_id on the wire — the
                // payload is {command, description, ...} and resolution is
                // FIFO via `approval.respond`. Track under a synthetic key
                // (or the id, should the server ever add one).
                let key = event
                    .payload
                    .get("request_id")
                    .and_then(JsonValue::as_str)
                    .unwrap_or("approval");
                self.open_requests.insert(key.to_owned());
            }
            _ => {}
        }
    }

    /// The signals to feed [`crate::state::derive_pet_state`] as of `now_ms`.
    pub fn signals(&self, now_ms: u64) -> ActivitySignals {
        let flash = self
            .flash
            .filter(|(_, until)| now_ms < *until)
            .map(|(kind, _)| kind);
        ActivitySignals {
            busy: self.busy,
            awaiting_input: !self.open_requests.is_empty(),
            error: flash == Some(Flash::Error),
            celebrate: flash == Some(Flash::Celebrate),
            just_completed: flash == Some(Flash::Greet),
            tool_running: self.tool_running && self.busy,
            reasoning: self.reasoning && self.busy,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{derive_pet_state, PetState};

    fn event(event_type: &str, payload: JsonValue) -> Event {
        Event {
            event_type: event_type.to_owned(),
            session_id: "abc123".to_owned(),
            payload,
        }
    }

    #[test]
    fn parses_event_frames() {
        let frame = r#"{"jsonrpc":"2.0","method":"event","params":{"type":"gateway.ready","payload":{"skin":"fabric"}}}"#;
        match parse_frame(frame) {
            Some(Incoming::Event(e)) => {
                assert_eq!(e.event_type, "gateway.ready");
                assert_eq!(e.session_id, "");
                assert_eq!(e.payload["skin"], "fabric");
            }
            other => panic!("unexpected: {other:?}"),
        }
    }

    #[test]
    fn parses_response_frames_and_ignores_junk() {
        let ok = r#"{"jsonrpc":"2.0","id":7,"result":{"session_id":"deadbeef"}}"#;
        assert!(matches!(parse_frame(ok), Some(Incoming::Response { .. })));
        let err =
            r#"{"jsonrpc":"2.0","id":8,"error":{"code":-32601,"message":"method not found"}}"#;
        assert!(matches!(parse_frame(err), Some(Incoming::Response { .. })));
        // Parse-error responses carry id: null — nothing for us to match.
        assert_eq!(
            parse_frame(r#"{"jsonrpc":"2.0","error":{"code":-32700},"id":null}"#),
            None
        );
        assert_eq!(parse_frame("not json"), None);
        assert_eq!(parse_frame(r#"{"jsonrpc":"2.0","method":"event"}"#), None);
    }

    #[test]
    fn request_frames_are_json_rpc() {
        let text = request_frame(3, "session.resume", serde_json::json!({"session_id": "s"}));
        let value: JsonValue = serde_json::from_str(&text).unwrap();
        assert_eq!(value["jsonrpc"], "2.0");
        assert_eq!(value["id"], 3);
        assert_eq!(value["method"], "session.resume");
        assert_eq!(value["params"]["session_id"], "s");
    }

    #[test]
    fn turn_lifecycle_walks_the_states() {
        let mut tracker = ActivityTracker::new();
        assert_eq!(derive_pet_state(tracker.signals(0)), PetState::Idle);

        tracker.apply(&event("message.start", JsonValue::Null), 0);
        assert_eq!(derive_pet_state(tracker.signals(0)), PetState::Run); // busy

        tracker.apply(&event("reasoning.delta", JsonValue::Null), 10);
        assert_eq!(derive_pet_state(tracker.signals(10)), PetState::Review);

        tracker.apply(&event("tool.start", JsonValue::Null), 20);
        assert_eq!(derive_pet_state(tracker.signals(20)), PetState::Run);

        tracker.apply(&event("tool.complete", JsonValue::Null), 30);
        assert_eq!(derive_pet_state(tracker.signals(30)), PetState::Run); // still busy

        tracker.apply(&event("message.complete", JsonValue::Null), 40);
        assert_eq!(derive_pet_state(tracker.signals(41)), PetState::Jump); // celebrate beat
        assert_eq!(
            derive_pet_state(tracker.signals(40 + CELEBRATE_FLASH_MS)),
            PetState::Idle // beat expired
        );
    }

    #[test]
    fn error_beat_replaces_celebrate_and_expires() {
        let mut tracker = ActivityTracker::new();
        tracker.apply(&event("message.complete", JsonValue::Null), 0);
        tracker.apply(&event("error", JsonValue::Null), 100);
        assert_eq!(derive_pet_state(tracker.signals(101)), PetState::Failed);
        // Single shared timer: celebrate was replaced, not layered.
        assert_eq!(
            derive_pet_state(tracker.signals(100 + ERROR_FLASH_MS)),
            PetState::Idle
        );
    }

    #[test]
    fn clean_finish_cannot_show_stale_error() {
        let mut tracker = ActivityTracker::new();
        tracker.apply(&event("error", JsonValue::Null), 0);
        tracker.apply(&event("message.complete", JsonValue::Null), 50);
        assert_eq!(derive_pet_state(tracker.signals(51)), PetState::Jump);
    }

    #[test]
    fn interrupted_turn_cannot_pin_run_or_review() {
        let mut tracker = ActivityTracker::new();
        tracker.apply(&event("message.start", JsonValue::Null), 0);
        tracker.apply(&event("tool.start", JsonValue::Null), 1);
        // Turn ends without a tool.complete (interrupt): steady flags are
        // gated on busy, so no stray RUN after the celebrate beat fades.
        tracker.apply(&event("message.complete", JsonValue::Null), 2);
        assert_eq!(
            derive_pet_state(tracker.signals(2 + CELEBRATE_FLASH_MS)),
            PetState::Idle
        );
    }

    #[test]
    fn interactive_requests_wait_on_the_user() {
        let mut tracker = ActivityTracker::new();
        tracker.apply(&event("message.start", JsonValue::Null), 0);
        tracker.apply(
            &event(
                "approval.request",
                serde_json::json!({"request_id": "r1", "command": "rm -rf /tmp/x"}),
            ),
            10,
        );
        assert_eq!(derive_pet_state(tracker.signals(10)), PetState::Waiting);

        tracker.resolve_request("r1");
        assert_eq!(derive_pet_state(tracker.signals(20)), PetState::Run);

        // Requests left dangling are cleared when the turn ends.
        tracker.apply(
            &event("clarify.request", serde_json::json!({"request_id": "r2"})),
            30,
        );
        tracker.apply(&event("message.complete", JsonValue::Null), 40);
        assert!(!tracker.signals(41).awaiting_input);
    }

    #[test]
    fn approval_requests_wait_without_a_request_id() {
        // approval.request payloads carry no request_id on the wire.
        let mut tracker = ActivityTracker::new();
        tracker.apply(&event("message.start", JsonValue::Null), 0);
        tracker.apply(&event("tool.start", JsonValue::Null), 5);
        tracker.apply(
            &event(
                "approval.request",
                serde_json::json!({"command": "rm -rf ./build", "description": "Delete build dir"}),
            ),
            10,
        );
        assert_eq!(derive_pet_state(tracker.signals(10)), PetState::Waiting);

        // The prompt resolving (answered elsewhere / timed out) surfaces as
        // the pending tool completing — WAITING must release.
        tracker.apply(&event("tool.complete", JsonValue::Null), 20);
        assert!(!tracker.signals(20).awaiting_input);
        assert_eq!(derive_pet_state(tracker.signals(20)), PetState::Run); // still busy
    }

    #[test]
    fn seeded_running_shows_activity_before_any_event() {
        let mut tracker = ActivityTracker::new();
        tracker.seed_running(true);
        assert_eq!(derive_pet_state(tracker.signals(0)), PetState::Run);
        tracker.apply(&event("message.complete", JsonValue::Null), 10);
        assert_eq!(
            derive_pet_state(tracker.signals(10 + CELEBRATE_FLASH_MS)),
            PetState::Idle
        );
    }

    #[test]
    fn greeting_waves() {
        let mut tracker = ActivityTracker::new();
        tracker.greet(1000);
        assert_eq!(derive_pet_state(tracker.signals(1500)), PetState::Wave);
        assert_eq!(
            derive_pet_state(tracker.signals(1000 + GREET_FLASH_MS)),
            PetState::Idle
        );
    }

    #[test]
    fn unknown_events_are_ignored() {
        let mut tracker = ActivityTracker::new();
        tracker.apply(
            &event("session.title", serde_json::json!({"title": "x"})),
            0,
        );
        tracker.apply(&event("some.future.event", JsonValue::Null), 0);
        assert_eq!(tracker.signals(0), ActivitySignals::default());
    }
}
