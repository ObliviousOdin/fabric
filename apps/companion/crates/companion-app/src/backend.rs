//! Spawn-your-own-backend support (`--spawn`), mirroring the Electron
//! desktop's bootstrap: run `fabric serve --host 127.0.0.1 --port 0` with a
//! pinned auth token in the child argv, then read the announced
//! port from its stdout ready line.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// Cold imports and Windows AV can delay a healthy first start for 30-60s.
const DEFAULT_READY_TIMEOUT: Duration = Duration::from_secs(90);
fn ready_timeout() -> Duration {
    DEFAULT_READY_TIMEOUT
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
        .args([
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--auth-token",
            token.as_str(),
        ])
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

/// Parse the server's structured readiness record.
fn parse_ready_line(line: &str) -> Option<u16> {
    let record: serde_json::Value = serde_json::from_str(line).ok()?;
    if record.get("type")?.as_str()? != "backend.ready" {
        return None;
    }
    let port = u16::try_from(record.get("port")?.as_u64()?).ok()?;
    (port > 0).then_some(port)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_lines() {
        assert_eq!(
            parse_ready_line(r#"{"type":"backend.ready","port":51234}"#),
            Some(51234)
        );
        assert_eq!(parse_ready_line("something else"), None);
        assert_eq!(
            parse_ready_line(r#"{"type":"backend.ready","port":"nope"}"#),
            None
        );
        assert_eq!(
            parse_ready_line(r#"{"type":"other.ready","port":51234}"#),
            None
        );
        assert_eq!(
            parse_ready_line(r#"{"type":"backend.ready","port":0}"#),
            None
        );
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
        assert_eq!(ready_timeout(), Duration::from_secs(90));
    }
}
