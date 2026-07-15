//! Spawn-your-own-backend support (`--spawn`), mirroring the Electron
//! desktop's bootstrap: run `fabric serve --host 127.0.0.1 --port 0` with a
//! pinned session token in the child environment, then read the announced
//! port from its stdout ready line.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// How long to wait for the backend's ready line before giving up.
const READY_TIMEOUT: Duration = Duration::from_secs(60);

/// The spawned backend process; killed when the companion exits.
pub struct BackendGuard(Child);

impl Drop for BackendGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// Generate a URL-safe random token (loopback session credential).
fn random_token() -> String {
    let mut token = String::with_capacity(64);
    for _ in 0..4 {
        token.push_str(&format!("{:016x}", fastrand::u64(..)));
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

    let stdout = child.stdout.take().expect("piped stdout");
    let mut reader = BufReader::new(stdout);
    let deadline = Instant::now() + READY_TIMEOUT;
    let mut line = String::new();
    loop {
        if Instant::now() > deadline {
            let _ = child.kill();
            return Err("backend never announced readiness".into());
        }
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => {
                let _ = child.kill();
                return Err("backend exited before announcing readiness".into());
            }
            Ok(_) => {
                if let Some(port) = parse_ready_line(line.trim()) {
                    // Keep draining stdout so the child never blocks on a
                    // full pipe.
                    std::thread::spawn(move || {
                        let mut sink = String::new();
                        while matches!(reader.read_line(&mut sink), Ok(n) if n > 0) {
                            sink.clear();
                        }
                    });
                    let url = format!("ws://127.0.0.1:{port}/api/ws?token={token}");
                    return Ok((url, BackendGuard(child)));
                }
            }
            Err(e) => {
                let _ = child.kill();
                return Err(format!("reading backend stdout: {e}"));
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
    fn tokens_are_long_and_hex() {
        let token = random_token();
        assert_eq!(token.len(), 64);
        assert!(token.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
