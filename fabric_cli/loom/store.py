"""Per-profile SQLite store for Loom (``$FABRIC_HOME/loom.db``).

Mirrors :mod:`fabric_cli.projects_db`: a WAL SQLite file opened with the shared
:mod:`fabric_cli.sqlite_util` primitives (idempotent column-add migrations and
IMMEDIATE write transactions). The schema is deliberately small and additive so
opening an older database is always safe.

The store persists three entities — hosts, projects, and deployments — as rows
with JSON blobs for the open-ended fields (host ``meta``, project ``config``,
deployment ``plan``). It performs no business logic; that lives in
:class:`fabric_cli.loom.service.LoomService`.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

from fabric_cli.loom.models import Deployment, Host, Plan, Project
from fabric_cli.sqlite_util import write_txn
from fabric_constants import get_fabric_home

# ---------------------------------------------------------------------------
# Paths and schema
# ---------------------------------------------------------------------------


def loom_db_path() -> Path:
    """The per-profile Loom DB path (``$FABRIC_HOME/loom.db``)."""
    return get_fabric_home() / "loom.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hosts (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL UNIQUE,
    kind                  TEXT NOT NULL,
    state                 TEXT NOT NULL,
    address               TEXT NOT NULL DEFAULT '',
    user                  TEXT NOT NULL DEFAULT '',
    port                  INTEGER NOT NULL DEFAULT 22,
    ssh_key_path          TEXT NOT NULL DEFAULT '',
    host_key_fingerprint  TEXT NOT NULL DEFAULT '',
    created_at            INTEGER NOT NULL,
    meta                  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT '',
    config      TEXT NOT NULL DEFAULT '{}',
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS deployments (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    host_id      TEXT NOT NULL,
    state        TEXT NOT NULL,
    source_ref   TEXT NOT NULL DEFAULT '',
    plan         TEXT NOT NULL DEFAULT '{}',
    active       INTEGER NOT NULL DEFAULT 0,
    previous_id  TEXT NOT NULL DEFAULT '',
    message      TEXT NOT NULL DEFAULT '',
    logs         TEXT NOT NULL DEFAULT '',
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deployments_project ON deployments(project_id);
CREATE INDEX IF NOT EXISTS idx_deployments_host ON deployments(host_id);
CREATE INDEX IF NOT EXISTS idx_deployments_active ON deployments(active);
"""


def _new_id(prefix: str) -> str:
    """A short, unguessable id, e.g. ``host_1a2b3c4d5e6f``."""
    return f"{prefix}_{secrets.token_hex(6)}"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class LoomStore:
    """A thin persistence layer over ``loom.db``.

    Pass an explicit ``db_path`` in tests; production callers use the default
    (the active profile's ``$FABRIC_HOME/loom.db``). The connection is opened
    once and reused; call :meth:`close` when done (the service does).
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = Path(db_path) if db_path is not None else loom_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "LoomStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- row mapping -------------------------------------------------------

    @staticmethod
    def _row_to_host(row: sqlite3.Row) -> Host:
        return Host(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            state=row["state"],
            address=row["address"],
            user=row["user"],
            port=int(row["port"]),
            ssh_key_path=row["ssh_key_path"],
            host_key_fingerprint=row["host_key_fingerprint"],
            created_at=int(row["created_at"]),
            meta=json.loads(row["meta"] or "{}"),
        )

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            source=row["source"],
            config=json.loads(row["config"] or "{}"),
            created_at=int(row["created_at"]),
        )

    @staticmethod
    def _row_to_deployment(row: sqlite3.Row) -> Deployment:
        return Deployment(
            id=row["id"],
            project_id=row["project_id"],
            host_id=row["host_id"],
            state=row["state"],
            source_ref=row["source_ref"],
            plan=Plan.from_dict(json.loads(row["plan"] or "{}")),
            active=bool(row["active"]),
            previous_id=row["previous_id"],
            message=row["message"],
            logs=row["logs"],
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    # -- hosts -------------------------------------------------------------

    def create_host(self, host: Host) -> Host:
        host.id = host.id or _new_id("host")
        host.created_at = host.created_at or int(time.time())
        with write_txn(self._conn):
            self._conn.execute(
                "INSERT INTO hosts (id, name, kind, state, address, user, port, "
                "ssh_key_path, host_key_fingerprint, created_at, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    host.id,
                    host.name,
                    host.kind,
                    host.state,
                    host.address,
                    host.user,
                    host.port,
                    host.ssh_key_path,
                    host.host_key_fingerprint,
                    host.created_at,
                    json.dumps(host.meta),
                ),
            )
        return host

    def update_host(self, host: Host) -> None:
        with write_txn(self._conn):
            self._conn.execute(
                "UPDATE hosts SET name=?, kind=?, state=?, address=?, user=?, "
                "port=?, ssh_key_path=?, host_key_fingerprint=?, meta=? WHERE id=?",
                (
                    host.name,
                    host.kind,
                    host.state,
                    host.address,
                    host.user,
                    host.port,
                    host.ssh_key_path,
                    host.host_key_fingerprint,
                    json.dumps(host.meta),
                    host.id,
                ),
            )

    def get_host(self, host_id: str) -> Optional[Host]:
        row = self._conn.execute(
            "SELECT * FROM hosts WHERE id=?", (host_id,)
        ).fetchone()
        return self._row_to_host(row) if row else None

    def get_host_by_name(self, name: str) -> Optional[Host]:
        row = self._conn.execute(
            "SELECT * FROM hosts WHERE name=?", (name,)
        ).fetchone()
        return self._row_to_host(row) if row else None

    def list_hosts(self) -> List[Host]:
        rows = self._conn.execute(
            "SELECT * FROM hosts ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_host(r) for r in rows]

    def delete_host(self, host_id: str) -> None:
        with write_txn(self._conn):
            self._conn.execute("DELETE FROM hosts WHERE id=?", (host_id,))

    # -- projects ----------------------------------------------------------

    def create_project(self, project: Project) -> Project:
        project.id = project.id or _new_id("proj")
        project.created_at = project.created_at or int(time.time())
        with write_txn(self._conn):
            self._conn.execute(
                "INSERT INTO projects (id, name, kind, source, config, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project.id,
                    project.name,
                    project.kind,
                    project.source,
                    json.dumps(project.config),
                    project.created_at,
                ),
            )
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        return self._row_to_project(row) if row else None

    def get_project_by_name(self, name: str) -> Optional[Project]:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE name=?", (name,)
        ).fetchone()
        return self._row_to_project(row) if row else None

    def list_projects(self) -> List[Project]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def delete_project(self, project_id: str) -> None:
        with write_txn(self._conn):
            self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))

    # -- deployments -------------------------------------------------------

    def create_deployment(self, dep: Deployment) -> Deployment:
        dep.id = dep.id or _new_id("dep")
        now = int(time.time())
        dep.created_at = dep.created_at or now
        dep.updated_at = now
        plan_json = json.dumps(dep.plan.to_dict() if dep.plan else {})
        with write_txn(self._conn):
            self._conn.execute(
                "INSERT INTO deployments (id, project_id, host_id, state, "
                "source_ref, plan, active, previous_id, message, logs, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dep.id,
                    dep.project_id,
                    dep.host_id,
                    dep.state,
                    dep.source_ref,
                    plan_json,
                    1 if dep.active else 0,
                    dep.previous_id,
                    dep.message,
                    dep.logs,
                    dep.created_at,
                    dep.updated_at,
                ),
            )
        return dep

    def update_deployment(self, dep: Deployment) -> None:
        dep.updated_at = int(time.time())
        plan_json = json.dumps(dep.plan.to_dict() if dep.plan else {})
        with write_txn(self._conn):
            self._conn.execute(
                "UPDATE deployments SET state=?, source_ref=?, plan=?, active=?, "
                "previous_id=?, message=?, logs=?, updated_at=? WHERE id=?",
                (
                    dep.state,
                    dep.source_ref,
                    plan_json,
                    1 if dep.active else 0,
                    dep.previous_id,
                    dep.message,
                    dep.logs,
                    dep.updated_at,
                    dep.id,
                ),
            )

    def get_deployment(self, dep_id: str) -> Optional[Deployment]:
        row = self._conn.execute(
            "SELECT * FROM deployments WHERE id=?", (dep_id,)
        ).fetchone()
        return self._row_to_deployment(row) if row else None

    def list_deployments(
        self, project_id: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Deployment]:
        sql = "SELECT * FROM deployments"
        params: list = []
        if project_id:
            sql += " WHERE project_id=?"
            params.append(project_id)
        sql += " ORDER BY created_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_deployment(r) for r in rows]

    def get_active_deployment(
        self, project_id: str, host_id: str
    ) -> Optional[Deployment]:
        row = self._conn.execute(
            "SELECT * FROM deployments WHERE project_id=? AND host_id=? AND active=1 "
            "ORDER BY created_at DESC LIMIT 1",
            (project_id, host_id),
        ).fetchone()
        return self._row_to_deployment(row) if row else None
