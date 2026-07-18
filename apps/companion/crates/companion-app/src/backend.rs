//! Spawn-your-own-backend support (`--spawn`), mirroring the Electron
//! desktop's bootstrap: run `fabric serve --host 127.0.0.1 --port 0` with a
//! pinned session token in the child environment, then read the announced
//! port from its stdout ready line.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// Cold imports and Windows AV can delay a healthy first start for 30-60s.
const DEFAULT_READY_TIMEOUT: Duration = Duration::from_secs(90);
/// Preserve the desktop's historical warm-start floor for bad overrides.
const MIN_READY_TIMEOUT: Duration = Duration::from_secs(45);
// public-release-audit: allow-legacy-compat -- mirror the desktop's existing cold-start override
const READY_TIMEOUT_ENV: &str = "HERMES_DESKTOP_PORT_ANNOUNCE_TIMEOUT_MS";

fn resolve_ready_timeout(raw: Option<&str>) -> Duration {
    let Some(milliseconds) = raw.and_then(|value| value.parse::<f64>().ok()) else {
        return DEFAULT_READY_TIMEOUT;
    };
    if !milliseconds.is_finite() || milliseconds <= 0.0 {
        return DEFAULT_READY_TIMEOUT;
    }
    Duration::from_millis(milliseconds.round() as u64).max(MIN_READY_TIMEOUT)
}

fn ready_timeout() -> Duration {
    resolve_ready_timeout(std::env::var(READY_TIMEOUT_ENV).ok().as_deref())
}

fn timeout_error(timeout: Duration) -> String {
    format!(
        "backend never announced readiness within {}ms",
        timeout.as_millis()
    )
}

/// The spawned backend process; killed when the companion exits.
pub struct BackendGuard(Child);

impl Drop for BackendGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// Generate a URL-safe random token (loopback session credential).
///
/// fastrand is not a CSPRNG, so mix in OS-level entropy sources the same way
/// for each chunk: the token guards a loopback-only, per-process backend, but
/// there is no reason to hand an attacker a guessable seed either.
fn random_token() -> String {
    use std::collections::hash_map::RandomState;
    use std::hash::{BuildHasher, Hasher};
    let mut token = String::with_capacity(64);
    for i in 0..4u64 {
        // RandomState draws its keys from the OS; hashing a rolling counter
        // through it yields unpredictable 64-bit chunks.
        let mut hasher = RandomState::new().build_hasher();
        hasher.write_u64(fastrand::u64(..) ^ i);
        token.push_str(&format!("{:016x}", hasher.finish()));
    }
    token
}

/// Spawn `fabric serve` and wait for its ready line. Returns the WebSocket
/// URL (token included) and the process guard.
pub fn spawn_backend(fabric_bin: &str) -> Result<(String, BackendGuard), String> {
    let token = random_token();
    let mut child = Command::new(fabric_bin)
        .args(["serve", "--host", "127.0.0.1", "--port", "0"])
        // public-release-audit: allow-legacy-compat -- the backend reads this exact pre-rename env name for the dashboard session token
        .env("HERMES_DASHBOARD_SESSION_TOKEN", &token)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .stdin(Stdio::null())
        .spawn()
        .map_err(|e| format!("failed to run `{fabric_bin} serve`: {e}"))?;

    // Read stdout on a helper thread: `read_line` has no timeout, so the
    // deadline below must not depend on the child ever producing output.
    // After the ready line is found (receiver dropped), the same thread
    // keeps draining stdout so the child never blocks on a full pipe.
    let stdout = child.stdout.take().expect("piped stdout");
    let (line_tx, line_rx) = std::sync::mpsc::channel::<String>();
    std::thread::Builder::new()
        .name("fabric-companion-backend-stdout".into())
        .spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut line = String::new();
            while matches!(reader.read_line(&mut line), Ok(n) if n > 0) {
                let _ = line_tx.send(std::mem::take(&mut line));
            }
        })
        .expect("spawn backend stdout thread");

    let timeout = ready_timeout();
    let deadline = Instant::now() + timeout;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            let _ = child.kill();
            let _ = child.wait();
            return Err(timeout_error(timeout));
        }
        match line_rx.recv_timeout(remaining) {
            Ok(line) => {
                if let Some(port) = parse_ready_line(line.trim()) {
                    let url = format!("ws://127.0.0.1:{port}/api/ws?token={token}");
                    return Ok((url, BackendGuard(child)));
                }
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(timeout_error(timeout));
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("backend exited before announcing readiness".into());
            }
        }
    }
}

/// Parse `HERMES_BACKEND_READY port=<n>` (legacy `HERMES_DASHBOARD_READY`).
fn parse_ready_line(line: &str) -> Option<u16> {
    // public-release-audit: allow-legacy-compat -- the backend announces readiness with these exact pre-rename stdout markers
    let rest = line.strip_prefix("HERMES_BACKEND_READY").or_else(|| {
        // public-release-audit: allow-legacy-compat -- legacy dashboard ready marker
        line.strip_prefix("HERMES_DASHBOARD_READY")
    })?;
    let port = rest.trim().strip_prefix("port=")?;
    port.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_lines() {
        // public-release-audit: allow-legacy-compat -- exercising the legacy ready markers
        assert_eq!(
            parse_ready_line("HERMES_BACKEND_READY port=51234"),
            Some(51234)
        );
        // public-release-audit: allow-legacy-compat -- exercising the legacy ready markers
        assert_eq!(
            parse_ready_line("HERMES_DASHBOARD_READY port=9119"),
            Some(9119)
        );
        assert_eq!(parse_ready_line("something else"), None);
        // public-release-audit: allow-legacy-compat -- exercising the legacy ready markers
        assert_eq!(parse_ready_line("HERMES_BACKEND_READY port=nope"), None);
    }

    #[test]
    fn tokens_are_long_hex_and_distinct() {
        let (a, b) = (random_token(), random_token());
        assert_eq!(a.len(), 64);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn ready_timeout_matches_desktop_cold_start_contract() {
        assert_eq!(resolve_ready_timeout(None), Duration::from_secs(90));
        assert_eq!(
            resolve_ready_timeout(Some("120000")),
            Duration::from_secs(120)
        );
        assert_eq!(resolve_ready_timeout(Some("1000")), Duration::from_secs(45));
        assert_eq!(
            resolve_ready_timeout(Some("60000.7")),
            Duration::from_millis(60_001)
        );
        for invalid in ["", "abc", "0", "-5", "NaN"] {
            assert_eq!(
                resolve_ready_timeout(Some(invalid)),
                Duration::from_secs(90)
            );
        }
    }
}
