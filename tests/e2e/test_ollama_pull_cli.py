"""Loopback E2E proof for the foreground ``fabric ollama pull`` command."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading


_MODEL = "qwen3:8b"
_DIGEST = "sha256:" + "a" * 64


class _OllamaHandler(BaseHTTPRequestHandler):
    tags_calls = 0
    pull_payloads: list[dict[str, object]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send_json(self, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        assert self.path == "/api/tags"
        type(self).tags_calls += 1
        models = []
        if type(self).tags_calls >= 2:
            models = [{"name": _MODEL, "digest": _DIGEST}]
        self._send_json({"models": models})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        assert self.path == "/api/pull"
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).pull_payloads.append(payload)
        body = (
            json.dumps(
                {
                    "status": "pulling manifest",
                    "digest": "sha256:" + "b" * 64,
                    "total": 10,
                    "completed": 10,
                },
                separators=(",", ":"),
            )
            + "\n"
            + json.dumps({"status": "success"}, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_cli_pull_streams_verifies_and_writes_sanitized_ledger(tmp_path: Path) -> None:
    _OllamaHandler.tags_calls = 0
    _OllamaHandler.pull_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    home = tmp_path / "home"
    fabric_root = home / ".fabric"
    profile_home = fabric_root / "profiles" / "local"
    profile_home.mkdir(parents=True)
    config_path = profile_home / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("FABRIC_HOME", None)
    env.pop("FABRIC_HOME", None)
    env.update({
        "HOME": str(home),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    })
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "fabric_cli.main",
                "-p",
                "local",
                "ollama",
                "pull",
                _MODEL,
                "--host",
                f"http://127.0.0.1:{server.server_port}",
                "--yes",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0, completed.stderr
    assert "installed and digest-verified" in completed.stdout
    assert "127.0.0.1" not in completed.stdout
    assert _OllamaHandler.pull_payloads == [{"model": _MODEL, "stream": True}]
    assert _OllamaHandler.tags_calls == 2

    ledgers = list((profile_home / "runtime" / "ollama-pulls").glob("*.json"))
    assert len(ledgers) == 1
    ledger = json.loads(ledgers[0].read_text(encoding="utf-8"))
    assert ledger["canonical_model"] == _MODEL
    assert ledger["phase"] == "ready"
    assert ledger["final_model_digest"] == _DIGEST
    assert ledger["exit_code"] == 0
    assert "endpoint" not in ledger
    assert "headers" not in ledger
    assert "credential" not in ledger
    assert config_path.read_text(encoding="utf-8") == "{}\n"
    assert not (profile_home / "state.db").exists()
    if os.name != "nt":
        assert stat.S_IMODE(ledgers[0].stat().st_mode) == 0o600
