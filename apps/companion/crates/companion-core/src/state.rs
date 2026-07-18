//! Map agent activity → a [`PetState`].
//!
//! Rust mirror of `agent/pet/state.py` (`derive_pet_state`), which is the
//! canonical implementation. The priority ladder below must stay byte-for-byte
//! faithful to the Python original; the shared conformance vectors in
//! `apps/companion/conformance/derive_pet_state.json` (exhaustive over all
//! 2^7 signal combinations, generated from the Python implementation) are
//! asserted by both `tests/agent/test_pet_state_vectors.py` and this crate's
//! `tests/conformance.rs`, so the mirrors cannot drift silently.

use serde::{Deserialize, Serialize};

/// Animation state a pet can be shown in.
///
/// These are Fabric's activity state names (see `PetState` in
/// `agent/pet/constants.py`). They are not always identical to the source
/// atlas row names: Codex-format pets use rows like `jumping` / `running`
/// while the UI keeps the shorter `jump` / `run` names.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PetState {
    Idle,
    Wave,
    Run,
    Failed,
    Review,
    Jump,
    Waiting,
}

impl PetState {
    /// The canonical wire/config name, matching the Python enum values.
    pub fn as_str(self) -> &'static str {
        match self {
            PetState::Idle => "idle",
            PetState::Wave => "wave",
            PetState::Run => "run",
            PetState::Failed => "failed",
            PetState::Review => "review",
            PetState::Jump => "jump",
            PetState::Waiting => "waiting",
        }
    }
}

/// Coarse activity signals a surface feeds into [`derive_pet_state`].
///
/// Each surface tracks these however it can — the CLI from its spinner state,
/// the TUI and desktop from gateway `tool.start/complete` +
/// `message.delta/complete` events. The companion overlay derives them from
/// the same gateway WebSocket stream (see the `gateway` module).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct ActivitySignals {
    pub busy: bool,
    pub awaiting_input: bool,
    pub error: bool,
    pub celebrate: bool,
    pub just_completed: bool,
    pub tool_running: bool,
    pub reasoning: bool,
}

/// Resolve the animation state from coarse activity signals.
///
/// Priority (highest first) — only one row can show at a time, so the most
/// salient signal wins:
///
/// 1. `error`          → `Failed`  (a tool/turn just failed)
/// 2. `celebrate`      → `Jump`    (explicit success beat, e.g. todos done)
/// 3. `just_completed` → `Wave`    (turn finished cleanly / greeting)
/// 4. `awaiting_input` → `Waiting` (blocked on the user — a clarify/approval
///    prompt is open; this outranks the in-flight signals below because the
///    turn is paused on *you*, even though a tool is technically mid-call)
/// 5. `tool_running`   → `Run`     (a tool is executing)
/// 6. `reasoning`      → `Review`  (model is thinking / reading)
/// 7. `busy`           → `Run`     (turn in flight, unspecified work)
/// 8. otherwise        → `Idle`
pub fn derive_pet_state(signals: ActivitySignals) -> PetState {
    if signals.error {
        return PetState::Failed;
    }
    if signals.celebrate {
        return PetState::Jump;
    }
    if signals.just_completed {
        return PetState::Wave;
    }
    if signals.awaiting_input {
        return PetState::Waiting;
    }
    if signals.tool_running {
        return PetState::Run;
    }
    if signals.reasoning {
        return PetState::Review;
    }
    if signals.busy {
        return PetState::Run;
    }
    PetState::Idle
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn idle_when_no_signals() {
        assert_eq!(derive_pet_state(ActivitySignals::default()), PetState::Idle);
    }

    #[test]
    fn error_outranks_everything() {
        let all_on = ActivitySignals {
            busy: true,
            awaiting_input: true,
            error: true,
            celebrate: true,
            just_completed: true,
            tool_running: true,
            reasoning: true,
        };
        assert_eq!(derive_pet_state(all_on), PetState::Failed);
    }

    #[test]
    fn waiting_outranks_in_flight_signals() {
        let signals = ActivitySignals {
            awaiting_input: true,
            tool_running: true,
            reasoning: true,
            busy: true,
            ..Default::default()
        };
        assert_eq!(derive_pet_state(signals), PetState::Waiting);
    }

    #[test]
    fn state_names_round_trip_through_serde() {
        for state in [
            PetState::Idle,
            PetState::Wave,
            PetState::Run,
            PetState::Failed,
            PetState::Review,
            PetState::Jump,
            PetState::Waiting,
        ] {
            let json = serde_json::to_string(&state).unwrap();
            assert_eq!(json, format!("\"{}\"", state.as_str()));
            let back: PetState = serde_json::from_str(&json).unwrap();
            assert_eq!(back, state);
        }
    }
}
