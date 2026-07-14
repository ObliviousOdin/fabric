"""Standard-library HTTP shell over :class:`LeaderboardStore`.

Zero third-party dependencies — this is deliberately runnable on any host
with a stock Python 3.11+, including a $5 VPS, a Tailscale node, or a
teammate's always-on box, without installing Fabric. All request logic lives
in :mod:`store`; this file only parses HTTP and serialises JSON.

Routes
------
    GET  /health                              -> {teams, members, ...}
    POST /api/teams                           -> create team
    POST /api/teams/{id}/join                 -> join team
    POST /api/teams/{id}/publish              -> publish aggregate profile
    POST /api/teams/{id}/leave                -> leave team
    GET  /api/teams/{id}/leaderboard          -> ranked roster
                                                 (auth via X-Join-Secret or
                                                  X-Member-Id + X-Member-Token)

Only Fabric *backends* (each member's dashboard, server-to-server via
urllib) call this service — browsers only ever talk to their own loopback
dashboard, which proxies. So there is no CORS surface and no cookie/session
handling here; auth is the per-team invite secret + per-member token defined
by the store.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .store import LeaderboardStore, RelayError

_log = logging.getLogger("fabric_achievements.relay")

MAX_BODY_BYTES = 256 * 1024  # generous for a bounded aggregate profile

_TEAM_JOIN_RE = re.compile(r"^/api/teams/([^/]+)/join$")
_TEAM_PUBLISH_RE = re.compile(r"^/api/teams/([^/]+)/publish$")
_TEAM_LEAVE_RE = re.compile(r"^/api/teams/([^/]+)/leave$")
_TEAM_ROTATE_RE = re.compile(r"^/api/teams/([^/]+)/rotate$")
_TEAM_KICK_RE = re.compile(r"^/api/teams/([^/]+)/kick$")
_TEAM_LEADERBOARD_RE = re.compile(r"^/api/teams/([^/]+)/leaderboard$")


class _Handler(BaseHTTPRequestHandler):
    # ``store`` is attached to the server instance in :func:`build_server`.
    server_version = "FabricLeaderboardRelay/1.0"

    @property
    def store(self) -> LeaderboardStore:
        return self.server.store  # type: ignore[attr-defined]

    # ---- low-level helpers --------------------------------------------
    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise RelayError("request body too large", status=413)
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - surface as 400
            raise RelayError(f"invalid JSON body: {exc}", status=400)
        if not isinstance(data, dict):
            raise RelayError("request body must be a JSON object", status=400)
        return data

    def _dispatch(self) -> Tuple[int, Dict[str, Any]]:
        path = self.path.split("?", 1)[0]
        method = self.command

        if method == "GET" and path == "/health":
            return 200, self.store.stats()

        if method == "POST" and path == "/api/teams":
            body = self._read_json_body()
            return 200, self.store.create_team(
                name=str(body.get("name", "")),
                display_name=str(body.get("display_name", "")),
            )

        m = _TEAM_JOIN_RE.match(path)
        if m and method == "POST":
            body = self._read_json_body()
            return 200, self.store.join_team(
                team_id=m.group(1),
                join_secret=str(body.get("join_secret", "")),
                display_name=str(body.get("display_name", "")),
            )

        m = _TEAM_PUBLISH_RE.match(path)
        if m and method == "POST":
            body = self._read_json_body()
            return 200, self.store.publish(
                team_id=m.group(1),
                member_id=str(body.get("member_id", "")),
                member_token=str(body.get("member_token", "")),
                profile=body.get("profile"),
                display_name=body.get("display_name"),
            )

        m = _TEAM_LEAVE_RE.match(path)
        if m and method == "POST":
            body = self._read_json_body()
            return 200, self.store.leave(
                team_id=m.group(1),
                member_id=str(body.get("member_id", "")),
                member_token=str(body.get("member_token", "")),
            )

        m = _TEAM_ROTATE_RE.match(path)
        if m and method == "POST":
            body = self._read_json_body()
            return 200, self.store.rotate_join_secret(
                team_id=m.group(1),
                member_id=str(body.get("member_id", "")),
                member_token=str(body.get("member_token", "")),
            )

        m = _TEAM_KICK_RE.match(path)
        if m and method == "POST":
            body = self._read_json_body()
            return 200, self.store.kick_member(
                team_id=m.group(1),
                member_id=str(body.get("member_id", "")),
                member_token=str(body.get("member_token", "")),
                target_member_id=str(body.get("target_member_id", "")),
            )

        m = _TEAM_LEADERBOARD_RE.match(path)
        if m and method == "GET":
            return 200, self.store.leaderboard(
                team_id=m.group(1),
                join_secret=self.headers.get("X-Join-Secret") or None,
                member_id=self.headers.get("X-Member-Id") or None,
                member_token=self.headers.get("X-Member-Token") or None,
            )

        raise RelayError("not found", status=404)

    def _handle(self) -> None:
        try:
            status, payload = self._dispatch()
            self._send_json(status, payload)
        except RelayError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to clients
            _log.exception("relay request failed")
            self._send_json(500, {"error": "internal error", "detail": str(exc)})

    # BaseHTTPRequestHandler dispatches by method name.
    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def log_message(self, fmt: str, *args: Any) -> None:
        # Route through logging instead of stderr; never log request bodies
        # (they carry secrets), only the request line the base class passes.
        _log.info("%s - %s", self.address_string(), fmt % args)


def build_server(host: str, port: int, store: LeaderboardStore) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.store = store  # type: ignore[attr-defined]
    return httpd


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fabric_achievements.relay",
        description="Run the Fabric Achievements leaderboard relay.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1; use 0.0.0.0 to expose)")
    parser.add_argument("--port", type=int, default=9137, help="bind port (default 9137)")
    parser.add_argument("--state", default=None, help="path to a JSON file to persist rosters (default: in-memory only)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = LeaderboardStore(path=Path(args.state) if args.state else None)
    httpd = build_server(args.host, args.port, store)
    _log.info("Fabric leaderboard relay listening on http://%s:%d", args.host, args.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log.info("shutting down")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via __main__.py
    raise SystemExit(main())
