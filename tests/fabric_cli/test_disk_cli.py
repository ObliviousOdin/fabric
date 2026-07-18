"""Tests for the ``fabric disk`` command (fabric_cli/disk.py).

Covers the usage report, the dry-run/confirm cleanup flow, the category
selection flags, and — most importantly — the invariant that ``clean`` never
deletes user data, credentials, config, databases, backups, or the cron
control-plane.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

import fabric_cli.disk as disk


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point the Fabric home at an isolated temp directory."""
    home = tmp_path / ".fabric"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("FABRIC_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return home


def _seed(home: Path, rel: str, size: int = 0, text: str | None = None) -> Path:
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        p.write_text(text)
    else:
        p.write_bytes(b"x" * size)
    return p


def _usage_args(**kw):
    base = dict(json_output=False, all=False, profile=None)
    base.update(kw)
    return Namespace(**base)


def _clean_args(**kw):
    base = dict(yes=False, force=False, only=None, skip=None)
    base.update(kw)
    return Namespace(**base)


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------

class TestUsage:
    def test_reports_categories_and_total(self, _isolate, capsys):
        _seed(_isolate, "cache/images/a.bin", 5_000_000)
        _seed(_isolate, "sessions/s.json", 1_000_000)
        disk.disk_usage(_usage_args())
        out = capsys.readouterr().out
        assert "Caches" in out
        assert "Sessions & state DB" in out
        assert "Total" in out
        # Caches (5 MB) should sort above Sessions (1 MB)
        assert out.index("Caches") < out.index("Sessions & state DB")

    def test_json_output(self, _isolate, capsys):
        _seed(_isolate, "cache/images/a.bin", 2_000_000)
        disk.disk_usage(_usage_args(json_output=True))
        data = json.loads(capsys.readouterr().out)
        assert "categories" in data
        assert "total_bytes" in data
        assert data["total_bytes"] >= 2_000_000
        keys = {c["key"] for c in data["categories"]}
        assert "cache" in keys

    def test_free_space_survives_disk_usage_failure(self, _isolate, capsys, monkeypatch):
        _seed(_isolate, "cache/x.bin", 1000)

        def _boom(*_a, **_k):
            raise OSError("no stat")

        monkeypatch.setattr(disk.shutil, "disk_usage", _boom)
        disk.disk_usage(_usage_args())  # must not raise
        out = capsys.readouterr().out
        assert "Total" in out
        assert "free of" not in out

    def test_hides_empty_by_default_shows_with_all(self, _isolate, capsys):
        # Nothing seeded → cache is empty.
        disk.disk_usage(_usage_args(all=False))
        assert "Caches" not in capsys.readouterr().out
        disk.disk_usage(_usage_args(all=True))
        assert "Caches" in capsys.readouterr().out

    def test_missing_profile_reports_gracefully(self, _isolate, capsys):
        disk.disk_usage(_usage_args(profile="ghost"))
        assert "No Fabric data found" in capsys.readouterr().out

    def test_json_stays_json_when_home_missing(self, _isolate, capsys):
        # --json must always emit parseable JSON, even for an absent profile.
        disk.disk_usage(_usage_args(json_output=True, profile="ghost"))
        data = json.loads(capsys.readouterr().out)
        assert data["total_bytes"] == 0
        assert data["categories"] == []

    def test_grand_total_equals_home_size_no_double_count(self, _isolate):
        # A top-level *_cache.json (matched by the cache glob) plus an
        # unclassified top-level file must sum to exactly the on-disk total —
        # no category may double-count into "Other".
        _seed(_isolate, "provider_models_cache.json", 4000)
        _seed(_isolate, "cache/images/a.bin", 5000)
        _seed(_isolate, "sessions/s.json", 3000)
        _seed(_isolate, "some_unknown_file.txt", 1000)
        usages = disk.scan_categories(_isolate)
        reported = sum(u.bytes for u in usages)
        actual = disk._path_size(_isolate)[0]
        assert reported == actual, (
            f"grand total {reported} != home size {actual} "
            "(double count or missed entry)"
        )
        # The cache json is attributed to Caches, not Other.
        other = next(u for u in usages if u.category.key == "other")
        assert other.bytes == 1000  # only the unknown file


# ---------------------------------------------------------------------------
# clean — dry run and basic behavior
# ---------------------------------------------------------------------------

class TestClean:
    def test_dry_run_default_deletes_nothing(self, _isolate, capsys):
        f = _seed(_isolate, "cache/images/a.bin", 5_000_000)
        rc = disk.disk_clean(_clean_args(yes=False))
        out = capsys.readouterr().out
        assert rc == 0
        assert "Dry run" in out
        assert "Would remove" in out
        assert f.exists()

    def test_yes_removes_cache_contents_keeps_dir(self, _isolate, capsys):
        f = _seed(_isolate, "cache/images/a.bin", 5_000_000)
        rc = disk.disk_clean(_clean_args(yes=True, force=True))
        out = capsys.readouterr().out
        assert rc == 0
        assert not f.exists()
        assert (_isolate / "cache").is_dir()  # protected dir kept
        assert "Freed" in out

    def test_removes_traces_tree(self, _isolate):
        _seed(_isolate, "moa-traces/t.json", 1000)
        _seed(_isolate, "spawn-trees/s.json", 1000)
        disk.disk_clean(_clean_args(yes=True, force=True))
        assert not (_isolate / "moa-traces").exists()
        assert not (_isolate / "spawn-trees").exists()

    def test_rotated_logs_removed_live_log_kept(self, _isolate):
        live = _seed(_isolate, "logs/agent.log", 1000)
        rotated = _seed(_isolate, "logs/agent.log.1", 2000)
        disk.disk_clean(_clean_args(yes=True, force=True))
        assert live.exists()
        assert not rotated.exists()

    def test_only_filter(self, _isolate):
        cache = _seed(_isolate, "cache/a.bin", 1000)
        trace = _seed(_isolate, "moa-traces/t.json", 1000)
        disk.disk_clean(_clean_args(yes=True, force=True, only=["cache"]))
        assert not cache.exists()
        assert trace.exists()  # not selected

    def test_skip_filter(self, _isolate):
        cache = _seed(_isolate, "cache/a.bin", 1000)
        trace = _seed(_isolate, "moa-traces/t.json", 1000)
        disk.disk_clean(_clean_args(yes=True, force=True, skip=["cache"]))
        assert cache.exists()  # skipped
        assert not trace.exists()

    def test_checkpoints_reported_not_cleaned(self, _isolate, capsys):
        ckpt = _seed(_isolate, "checkpoints/sess/c.tar", 1000)
        # checkpoints is report-only: `clean` never removes it and instead
        # points at the dedicated command.
        disk.disk_clean(_clean_args(yes=True, force=True))
        assert ckpt.exists()
        # And it is not an accepted --only value (not reclaimable).
        assert "checkpoints" not in disk.RECLAIMABLE_KEYS

    def test_checkpoints_tip_in_dry_run(self, _isolate, capsys):
        _seed(_isolate, "checkpoints/sess/c.tar", 5000)
        _seed(_isolate, "cache/a.bin", 1000)
        disk.disk_clean(_clean_args(yes=False))
        assert "fabric checkpoints prune" in capsys.readouterr().out

    def test_nothing_to_reclaim(self, _isolate, capsys):
        disk.disk_clean(_clean_args(yes=True, force=True))
        assert "Nothing to reclaim" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# clean — the critical safety invariants
# ---------------------------------------------------------------------------

class TestCleanSafety:
    PROTECTED = [
        "state.db",
        "state.db-wal",
        "sessions/s.json",
        "memories/MEMORY.md",
        ".env",
        "auth.json",
        "provider-accounts.json",
        "config.yaml",
        "cron/jobs.json",
        "cron/.tick.lock",
        "cron/output/j/run.txt",
        "backups/b.zip",
        "state-snapshots/snap/x",
        "plugins/p/plugin.yaml",
        "skills/s/SKILL.md",
        "platforms/whatsapp/session/creds.json",
        "disk-cleanup/tracked.json",
        "projects.db",
        "kanban.db",
        "checkpoints/sess/c.tar",
    ]

    def test_never_deletes_protected_paths(self, _isolate):
        for rel in self.PROTECTED:
            _seed(_isolate, rel, text="keep")
        # Run every reclaimable category, forced, no filters holding back.
        disk.disk_clean(_clean_args(yes=True, force=True))
        missing = [rel for rel in self.PROTECTED if not (_isolate / rel).exists()]
        assert missing == [], f"cleanup deleted protected paths: {missing}"

    def test_guard_rejects_paths_outside_home(self, _isolate, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("x")
        assert disk._is_clean_safe(outside, _isolate) is False

    def test_guard_rejects_protected_top_level(self, _isolate):
        assert disk._is_clean_safe(_isolate / "state.db", _isolate) is False
        assert disk._is_clean_safe(_isolate / "sessions" / "s.json", _isolate) is False
        assert disk._is_clean_safe(_isolate / "cron" / "jobs.json", _isolate) is False

    def test_guard_allows_reclaimable(self, _isolate):
        assert disk._is_clean_safe(_isolate / "cache" / "img.png", _isolate) is True
        assert disk._is_clean_safe(_isolate / "moa-traces", _isolate) is True
        assert disk._is_clean_safe(_isolate / "logs" / "agent.log.1", _isolate) is True
        assert disk._is_clean_safe(_isolate / "provider_models_cache.json", _isolate) is True

    def test_guard_glob_is_depth_anchored(self, _isolate):
        # A cache-glob ("*_cache.json") must NOT match a nested file under a
        # protected directory, and a "logs/*.log.*" glob must NOT match deeper
        # than a direct child of logs/. (Regression: fnmatch '*' crossing '/'.)
        assert disk._is_clean_safe(_isolate / "mcp-tokens" / "oauth_cache.json", _isolate) is False
        assert disk._is_clean_safe(_isolate / "sessions" / "history_cache.json", _isolate) is False
        assert disk._is_clean_safe(_isolate / "logs" / "sub" / "live.log.keep", _isolate) is False


# ---------------------------------------------------------------------------
# clean — confirmation / non-interactive
# ---------------------------------------------------------------------------

class TestConfirm:
    def test_noninteractive_without_force_aborts(self, _isolate, monkeypatch, capsys):
        _seed(_isolate, "cache/a.bin", 1000)
        monkeypatch.setattr(disk.sys.stdin, "isatty", lambda: False)
        rc = disk.disk_clean(_clean_args(yes=True, force=False))
        assert rc == 2
        assert (_isolate / "cache" / "a.bin").exists()
        assert "non-interactive" in capsys.readouterr().err

    def test_interactive_confirm_yes(self, _isolate, monkeypatch):
        f = _seed(_isolate, "cache/a.bin", 1000)
        monkeypatch.setattr(disk.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *_a: "yes")
        disk.disk_clean(_clean_args(yes=True, force=False))
        assert not f.exists()

    def test_interactive_confirm_no(self, _isolate, monkeypatch):
        f = _seed(_isolate, "cache/a.bin", 1000)
        monkeypatch.setattr(disk.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *_a: "no")
        rc = disk.disk_clean(_clean_args(yes=True, force=False))
        assert rc == 1
        assert f.exists()


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_bare_disk_prints_help(self, capsys):
        class _P:
            def print_help(self):
                print("HELP TEXT")

        rc = disk.disk_command(Namespace(disk_command=None, _disk_parser=_P()))
        assert rc == 0
        assert "HELP TEXT" in capsys.readouterr().out

    def test_usage_alias_du(self, _isolate, capsys):
        _seed(_isolate, "cache/a.bin", 1000)
        rc = disk.disk_command(
            _usage_args(disk_command="du")
        )
        assert rc == 0
        assert "Fabric disk usage" in capsys.readouterr().out

    def test_clean_routes(self, _isolate, capsys):
        _seed(_isolate, "cache/a.bin", 1000)
        rc = disk.disk_command(_clean_args(disk_command="clean", yes=False))
        assert rc == 0
        assert "Dry run" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# parser integration — build the subparser exactly as fabric_cli/main.py does
# ---------------------------------------------------------------------------

class TestParserWiring:
    @staticmethod
    def _parser():
        import argparse

        from fabric_cli.subcommands.disk import build_disk_parser

        top = argparse.ArgumentParser(prog="fabric")
        subparsers = top.add_subparsers(dest="command")
        sentinel = object()
        build_disk_parser(subparsers, cmd_disk=sentinel)
        return top, sentinel

    def test_usage_flags_and_dispatch(self):
        top, sentinel = self._parser()
        args = top.parse_args(["disk", "usage", "--json", "--all", "--profile", "coder"])
        assert args.func is sentinel
        assert args.disk_command == "usage"
        assert args.json_output is True
        assert args.all is True
        assert args.profile == "coder"
        assert hasattr(args, "_disk_parser")

    def test_usage_alias_du_parses(self):
        top, _ = self._parser()
        args = top.parse_args(["disk", "du"])
        assert args.disk_command == "du"

    def test_clean_flags(self):
        top, _ = self._parser()
        args = top.parse_args(
            ["disk", "clean", "--yes", "--force", "--only", "cache", "logs"]
        )
        assert args.disk_command == "clean"
        assert args.yes is True
        assert args.force is True
        assert args.only == ["cache", "logs"]

    def test_clean_rejects_unknown_category(self):
        top, _ = self._parser()
        with pytest.raises(SystemExit):
            top.parse_args(["disk", "clean", "--only", "sessions"])

    def test_bare_disk_sets_parser_default(self):
        top, sentinel = self._parser()
        args = top.parse_args(["disk"])
        assert args.func is sentinel
        assert getattr(args, "disk_command", None) is None
        assert hasattr(args, "_disk_parser")
