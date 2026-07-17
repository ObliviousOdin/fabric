from io import StringIO
import json
import threading
from unittest.mock import patch

import pytest
from rich.console import Console

from cli import ChatConsole
from fabric_cli.skills_hub import (
    SkillInstallOutcome,
    do_check,
    do_gc,
    do_install,
    do_list,
    do_snapshot_export,
    do_snapshot_import,
    do_update,
    handle_skills_slash,
)


class _DummyLockFile:
    def __init__(self, installed):
        self._installed = installed

    def list_installed(self):
        return self._installed


@pytest.fixture()
def hub_env(monkeypatch, tmp_path):
    """Set up isolated hub directory paths and return (monkeypatch, tmp_path)."""
    import tools.skills_hub as hub

    hub_dir = tmp_path / "skills" / ".hub"
    monkeypatch.setattr(hub, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(hub, "HUB_DIR", hub_dir)
    monkeypatch.setattr(hub, "LOCK_FILE", hub_dir / "lock.json")
    monkeypatch.setattr(hub, "QUARANTINE_DIR", hub_dir / "quarantine")
    monkeypatch.setattr(hub, "AUDIT_LOG", hub_dir / "audit.log")
    monkeypatch.setattr(hub, "TAPS_FILE", hub_dir / "taps.json")
    monkeypatch.setattr(hub, "INDEX_CACHE_DIR", hub_dir / "index-cache")

    return hub_dir


# ---------------------------------------------------------------------------
# Fixtures for common skill setups
# ---------------------------------------------------------------------------

_HUB_ENTRY = {
    "name": "hub-skill",
    "source": "github",
    "identifier": "example/repo/hub-skill",
    "trust_level": "community",
}

_ALL_THREE_SKILLS = [
    {"name": "hub-skill", "category": "x", "description": "hub"},
    {"name": "builtin-skill", "category": "x", "description": "builtin"},
    {"name": "local-skill", "category": "x", "description": "local"},
]

_BUILTIN_MANIFEST = {"builtin-skill": "abc123"}


def _exact_snapshot_skill(name: str, identifier: str) -> dict:
    return {
        "name": name,
        "source_name": name,
        "source_revision": identifier,
        "authority": {
            "adapter": "github",
            "remote_identifier": identifier,
            "bundle_source": "github",
            "trust_level": "community",
        },
        "digest": "0" * 64,
        "category": "",
    }


@pytest.fixture()
def three_source_env(monkeypatch, hub_env):
    """Populate hub/builtin/local skills for source-classification tests."""
    import tools.skills_hub as hub
    import tools.skills_sync as skills_sync
    import tools.skills_tool as skills_tool

    monkeypatch.setattr(hub, "HubLockFile", lambda: _DummyLockFile([_HUB_ENTRY]))
    monkeypatch.setattr(skills_tool, "_find_all_skills", lambda **_kwargs: list(_ALL_THREE_SKILLS))
    monkeypatch.setattr(skills_sync, "_read_manifest", lambda: dict(_BUILTIN_MANIFEST))

    return hub_env


def _capture(source_filter: str = "all") -> str:
    """Run do_list into a string buffer and return the output."""
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    do_list(source_filter=source_filter, console=console)
    return sink.getvalue()


def _capture_check(monkeypatch, results, name=None) -> str:
    import tools.skills_hub as hub

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    monkeypatch.setattr(hub, "check_for_skill_updates", lambda **_kwargs: results)
    do_check(name=name, console=console)
    return sink.getvalue()


def _capture_update(monkeypatch, results) -> tuple[str, list[tuple[str, str, bool]]]:
    import tools.skills_hub as hub
    import fabric_cli.skills_hub as cli_hub

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    installs = []

    checked_results = []
    for result in results:
        checked = dict(result)
        if checked.get("status") == "update_available":
            checked["checked_candidate"] = {
                "installed_entry": {
                    "install_path": "category/" + checked["name"]
                }
            }
        checked_results.append(checked)
    monkeypatch.setattr(
        hub,
        "check_for_skill_updates",
        lambda **_kwargs: checked_results,
    )

    def successful_install(
        identifier, category="", force=False, console=None, **_kwargs
    ):
        installs.append((identifier, category, force))
        return SkillInstallOutcome(
            installed=True,
            name=identifier.rsplit("/", 1)[-1],
            message="Installed successfully.",
        )

    monkeypatch.setattr(cli_hub, "do_install", successful_install)

    do_update(console=console)
    return sink.getvalue(), installs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_do_list_initializes_hub_dir(monkeypatch, hub_env):
    import tools.skills_sync as skills_sync
    import tools.skills_tool as skills_tool

    monkeypatch.setattr(skills_tool, "_find_all_skills", lambda **_kwargs: [])
    monkeypatch.setattr(skills_sync, "_read_manifest", lambda: {})

    hub_dir = hub_env
    assert not hub_dir.exists()

    _capture()

    assert hub_dir.exists()
    assert (hub_dir / "lock.json").exists()
    assert (hub_dir / "quarantine").is_dir()
    assert (hub_dir / "index-cache").is_dir()


def test_do_list_distinguishes_hub_builtin_and_local(three_source_env):
    output = _capture()

    assert "hub-skill" in output
    assert "builtin-skill" in output
    assert "local-skill" in output
    assert "1 hub-installed, 1 builtin, 1 local" in output


def test_do_list_never_labels_unverified_official_claim_as_official(
    monkeypatch, hub_env
):
    import tools.skills_hub as hub
    import tools.skills_sync as skills_sync
    import tools.skills_tool as skills_tool

    entry = {
        "name": "spoofed-source",
        "source": "official",
        "identifier": "official/spoofed-source",
        "trust_level": "community",
        "source_authority": {
            "adapter": "unverified",
            "remote_identifier": "official/spoofed-source",
            "bundle_source": "official",
            "trust_level": "community",
        },
    }
    monkeypatch.setattr(hub, "HubLockFile", lambda: _DummyLockFile([entry]))
    monkeypatch.setattr(
        skills_tool,
        "_find_all_skills",
        lambda **_kwargs: [
            {"name": "spoofed-source", "category": "", "description": ""}
        ],
    )
    monkeypatch.setattr(skills_sync, "_read_manifest", lambda: {})

    output = _capture()

    assert "unverified" in output
    assert "community" in output
    assert "official" not in output


def test_do_list_filter_local(three_source_env):
    output = _capture(source_filter="local")

    assert "local-skill" in output
    assert "builtin-skill" not in output
    assert "hub-skill" not in output


def test_do_list_filter_hub(three_source_env):
    output = _capture(source_filter="hub")

    assert "hub-skill" in output
    assert "builtin-skill" not in output
    assert "local-skill" not in output


def test_do_list_filter_builtin(three_source_env):
    output = _capture(source_filter="builtin")

    assert "builtin-skill" in output
    assert "hub-skill" not in output
    assert "local-skill" not in output


def test_do_list_renders_status_column(three_source_env, monkeypatch):
    """Every list row should carry an enabled/disabled status (new in PR that
    answered Mr Mochizuki's 'I just want to see what's live' question)."""
    from agent import skill_utils

    monkeypatch.setattr(skill_utils, "get_disabled_skill_names", lambda platform=None: set())
    output = _capture()

    assert "Status" in output
    assert "enabled" in output.lower()
    # Summary counts enabled skills.
    assert "3 enabled, 0 disabled" in output


def test_do_list_marks_disabled_skills(three_source_env, monkeypatch):
    from agent import skill_utils

    # Simulate `skills.disabled: [hub-skill]` in config.
    monkeypatch.setattr(
        skill_utils, "get_disabled_skill_names",
        lambda platform=None: {"hub-skill"},
    )
    output = _capture()

    # Row still appears (no --enabled-only), but marked disabled
    assert "hub-skill" in output
    assert "disabled" in output.lower()
    assert "2 enabled, 1 disabled" in output


def test_do_list_enabled_only_hides_disabled(three_source_env, monkeypatch):
    from agent import skill_utils

    monkeypatch.setattr(
        skill_utils, "get_disabled_skill_names",
        lambda platform=None: {"hub-skill"},
    )
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    do_list(enabled_only=True, console=console)
    output = sink.getvalue()

    assert "hub-skill" not in output
    assert "builtin-skill" in output
    assert "local-skill" in output
    assert "enabled only" in output.lower()
    assert "2 enabled shown" in output


def test_do_list_platform_env_is_ignored(three_source_env, monkeypatch):
    """`fabric skills list` reads the active profile's config via
    FABRIC_HOME (swapped by -p), so it must NOT pass a platform arg to
    ``get_disabled_skill_names`` — otherwise per-platform overrides
    would silently leak in from FABRIC_PLATFORM env."""
    from agent import skill_utils

    seen = {}

    def _fake(platform=None):
        seen["platform"] = platform
        return set()

    monkeypatch.setattr(skill_utils, "get_disabled_skill_names", _fake)
    _capture()

    assert seen["platform"] is None


def test_do_check_reports_available_updates(monkeypatch):
    output = _capture_check(monkeypatch, [
        {"name": "hub-skill", "source": "skills.sh", "status": "update_available"},
        {"name": "other-skill", "source": "github", "status": "up_to_date"},
    ])

    assert "hub-skill" in output
    assert "update_available" in output
    assert "up_to_date" in output


def test_do_check_handles_no_installed_updates(monkeypatch):
    output = _capture_check(monkeypatch, [])

    assert "No hub-installed skills to check" in output


def test_do_gc_reports_bounded_cleanup_result(monkeypatch):
    import tools.skills_hub as hub

    monkeypatch.setattr(
        hub,
        "gc_hub_transaction_artifacts",
        lambda: {
            "removed": 3,
            "retained": 1,
            "transactions_removed": 2,
            "transactions_retained": 1,
            "truncated": 1,
        },
    )
    sink = StringIO()
    result = do_gc(
        console=Console(file=sink, force_terminal=False, color_system=None)
    )

    assert result["transactions_removed"] == 2
    assert "2 transaction record(s)" in sink.getvalue()
    assert "1 transaction record(s) retained" in sink.getvalue()
    assert "run `fabric skills gc` again" in sink.getvalue().lower()


def test_do_update_reinstalls_outdated_skills(monkeypatch):
    output, installs = _capture_update(monkeypatch, [
        {"name": "hub-skill", "identifier": "skills-sh/example/repo/hub-skill", "status": "update_available"},
        {"name": "other-skill", "identifier": "github/example/other-skill", "status": "up_to_date"},
    ])

    assert installs == [("skills-sh/example/repo/hub-skill", "category", True)]
    assert "Update result: 1 applied, 0 refused/failed" in output


def test_do_update_reports_each_refused_outcome_truthfully(monkeypatch):
    import tools.skills_hub as hub
    import fabric_cli.skills_hub as cli_hub

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    monkeypatch.setattr(
        hub,
        "check_for_skill_updates",
        lambda **_kwargs: [
            {
                "name": "blocked",
                "identifier": "source/blocked",
                "status": "update_available",
                "checked_candidate": {
                    "installed_entry": {"install_path": "blocked"}
                },
            },
            {
                "name": "updated",
                "identifier": "source/updated",
                "status": "update_available",
                "checked_candidate": {
                    "installed_entry": {"install_path": "updated"}
                },
            },
        ],
    )
    outcomes = iter((
        SkillInstallOutcome(False, "blocked", "ownership changed"),
        SkillInstallOutcome(True, "updated", "Installed successfully."),
    ))
    monkeypatch.setattr(cli_hub, "do_install", lambda *args, **kwargs: next(outcomes))

    do_update(console=console)
    output = sink.getvalue()

    assert "Update not applied: blocked — ownership changed" in output
    assert "Update result: 1 applied, 1 refused/failed" in output


def test_checked_update_install_never_reconsults_source_router(
    monkeypatch, tmp_path, hub_env
):
    import tools.skills_guard as guard
    import tools.skills_hub as hub

    bundle = hub.SkillBundle(
        name="checked",
        files={"SKILL.md": "# checked bytes\n"},
        source="github",
        identifier="owner/repo/checked",
        trust_level="community",
    )
    authority = hub.source_authority_for_adapter(
        hub.GitHubSource(auth=hub.GitHubAuth()),
        bundle,
    )
    installed = {
        "source": "github",
        "identifier": bundle.identifier,
        "trust_level": authority.trust_level,
        "source_authority": authority.as_dict(),
        "scan_verdict": "safe",
        "content_hash": "sha256:old",
        "attested_tree_sha256": "0" * 64,
        "install_path": "checked",
        "files": ["SKILL.md"],
        "metadata": {},
        "installed_at": "then",
        "updated_at": "then",
    }
    candidate = {
        "authority": authority.as_dict(),
        "bundle": bundle,
        "installed_entry": {"name": bundle.name, **installed},
        "latest_hash": hub.bundle_content_hash(bundle),
        "snapshot_identity": hub.bundle_snapshot_identity(bundle),
        "source_name": bundle.name,
        "source_revision": hub.bundle_source_revision(bundle),
    }
    quarantine = tmp_path / "skills" / ".hub" / "quarantine" / "checked"
    quarantine.mkdir(parents=True)
    (quarantine / "SKILL.md").write_text("# checked bytes\n")

    monkeypatch.setattr(hub, "ensure_hub_dirs", lambda: None)
    monkeypatch.setattr(
        hub,
        "create_source_router",
        lambda _auth: (_ for _ in ()).throw(
            AssertionError("router must not be consulted")
        ),
    )
    monkeypatch.setattr(hub, "quarantine_bundle", lambda _bundle: quarantine)
    monkeypatch.setattr(
        hub,
        "HubLockFile",
        lambda: type(
            "Lock",
            (),
            {"get_installed": lambda self, _name: installed},
        )(),
    )
    monkeypatch.setattr(
        hub,
        "scan_skill_with_authority",
        lambda _path, typed_authority: guard.ScanResult(
            skill_name=bundle.name,
            source=typed_authority.scan_source,
            trust_level=typed_authority.trust_level,
            verdict="safe",
        ),
    )
    monkeypatch.setattr(
        guard,
        "should_allow_install",
        lambda _result, force=False: (False, "stop after continuity proof"),
    )
    monkeypatch.setattr(guard, "format_scan_report", lambda _result: "scan ok")

    outcome = do_install(
        bundle.identifier,
        force=True,
        skip_confirm=True,
        checked_update=candidate,
    )
    assert outcome.installed is False
    assert "stop after continuity proof" in outcome.message


def test_snapshot_import_reports_refused_and_missing_entries(monkeypatch, tmp_path):
    import fabric_cli.skills_hub as cli_hub

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps({
            "schema_version": 2,
            "skills": [
                _exact_snapshot_skill("ok", "source/repo/ok"),
                _exact_snapshot_skill("blocked", "source/repo/blocked"),
            ],
            "taps": [],
        })
    )
    outcomes = iter((
        SkillInstallOutcome(True, "ok", "Installed successfully."),
        SkillInstallOutcome(False, "blocked", "local destination owned"),
    ))
    monkeypatch.setattr(cli_hub, "do_install", lambda *args, **kwargs: next(outcomes))
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)

    do_snapshot_import(str(snapshot_path), console=console)
    output = sink.getvalue()

    assert "Snapshot entry not installed: blocked — local destination owned" in output
    assert "Snapshot import result: 1 installed, 1 refused/failed" in output


@pytest.mark.parametrize(
    "document",
    (
        [],
        {},
        {"skills": {}, "taps": []},
        {"skills": ["not-an-object"], "taps": []},
        {"skills": [], "taps": [{"repo": 42}]},
        {"skills": [], "taps": [], "unexpected": True},
        {
            "skills": [
                {
                    "name": "missing-category",
                    "source": "github",
                    "identifier": "owner/repo/skill",
                }
            ],
            "taps": [],
        },
        {
            "skills": [],
            "taps": [
                {
                    "repo": "owner/repo",
                    "path": "skills/",
                    "trust": "builtin",
                }
            ],
        },
    ),
)
def test_snapshot_import_rejects_malformed_schema(monkeypatch, tmp_path, document):
    import fabric_cli.skills_hub as cli_hub

    snapshot_path = tmp_path / "malformed.json"
    snapshot_path.write_text(json.dumps(document), encoding="utf-8")
    called = False

    def unexpected_install(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(cli_hub, "do_install", unexpected_install)
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)

    do_snapshot_import(str(snapshot_path), console=console)

    assert "Invalid snapshot" in sink.getvalue()
    assert called is False


@pytest.mark.parametrize("schema_version", (1, 3))
def test_snapshot_import_rejects_backward_and_newer_schema(
    monkeypatch, tmp_path, schema_version
):
    import fabric_cli.skills_hub as cli_hub

    snapshot_path = tmp_path / "versioned.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "skills": [],
                "taps": [],
            }
        ),
        encoding="utf-8",
    )
    called = False

    def unexpected_install(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(cli_hub, "do_install", unexpected_install)
    sink = StringIO()
    do_snapshot_import(
        str(snapshot_path),
        console=Console(file=sink, force_terminal=False, color_system=None),
    )

    assert "must be exactly 2" in sink.getvalue()
    assert called is False


def test_snapshot_import_counts_only_committed_new_taps(monkeypatch, tmp_path):
    import tools.skills_hub as hub

    snapshot_path = tmp_path / "taps.json"
    snapshot_path.write_text(
        json.dumps({
            "schema_version": 2,
            "skills": [],
            "taps": [
                {"repo": "new/repo", "path": "skills/"},
                {"repo": "existing/repo", "path": "skills/"},
                {"repo": "pending/repo", "path": "skills/"},
            ],
        }),
        encoding="utf-8",
    )
    outcomes = iter((
        hub.HubMetadataMutationOutcome("committed", "added", changed=True),
        hub.HubMetadataMutationOutcome(
            "committed", "already configured", changed=False
        ),
        hub.HubMetadataMutationOutcome("recovery_pending", "durability pending"),
    ))
    monkeypatch.setattr(
        hub,
        "TapsManager",
        lambda: type("Taps", (), {"add": lambda self, *args: next(outcomes)})(),
    )
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)

    do_snapshot_import(str(snapshot_path), console=console)
    output = sink.getvalue()

    assert "Tap restore result: 1 added, 2 refused/unchanged" in output
    assert "already configured" in output
    assert "durability pending" in output


def test_snapshot_import_turns_tap_exception_into_typed_refusal(monkeypatch, tmp_path):
    import tools.skills_hub as hub

    snapshot_path = tmp_path / "tap-error.json"
    snapshot_path.write_text(
        json.dumps({
            "schema_version": 2,
            "skills": [],
            "taps": [{"repo": "owner/repo", "path": "skills/"}],
        }),
        encoding="utf-8",
    )

    def fail_add(*_args, **_kwargs):
        raise OSError("tap storage unavailable")

    monkeypatch.setattr(
        hub,
        "TapsManager",
        lambda: type("Taps", (), {"add": fail_add})(),
    )
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)

    do_snapshot_import(str(snapshot_path), console=console)

    output = sink.getvalue()
    assert "Tap restore result: 0 added, 1 refused/unchanged" in output
    assert "tap storage unavailable" in output


def test_snapshot_import_rejects_oversized_document_before_json_parse(
    monkeypatch, tmp_path
):
    import fabric_cli.skills_hub as cli_hub

    snapshot_path = tmp_path / "oversized.json"
    snapshot_path.write_text("{" + (" " * 64) + "}", encoding="utf-8")
    monkeypatch.setattr(cli_hub, "_MAX_SNAPSHOT_JSON_BYTES", 16)
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)

    do_snapshot_import(str(snapshot_path), console=console)

    output = sink.getvalue()
    assert "snapshot exceeds" in output
    assert "16 bytes" in output


def test_snapshot_import_rejects_growth_after_descriptor_stat(monkeypatch, tmp_path):
    import fabric_cli.skills_hub as cli_hub

    snapshot_path = tmp_path / "growing.json"
    snapshot_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli_hub, "_MAX_SNAPSHOT_JSON_BYTES", 16)
    real_read = cli_hub.os.read
    grew = False

    def grow_before_first_read(descriptor, size):
        nonlocal grew
        if not grew:
            grew = True
            snapshot_path.write_bytes(b"{" + (b" " * 31) + b"}")
        return real_read(descriptor, size)

    monkeypatch.setattr(cli_hub.os, "read", grow_before_first_read)
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)

    do_snapshot_import(str(snapshot_path), console=console)

    assert grew is True
    output = sink.getvalue()
    assert "snapshot exceeds" in output
    assert "16 bytes" in output


def test_handle_skills_slash_search_accepts_chatconsole_without_status_errors():
    results = [
        type(
            "R",
            (),
            {
                "name": "kubernetes",
                "description": "Cluster orchestration",
                "source": "skills.sh",
                "trust_level": "community",
                "identifier": "skills-sh/example/kubernetes",
            },
        )()
    ]

    with (
        patch("tools.skills_hub.unified_search", return_value=results),
        patch("tools.skills_hub.create_source_router", return_value={}),
        patch("tools.skills_hub.GitHubAuth"),
    ):
        handle_skills_slash("/skills search kubernetes", console=ChatConsole())


def test_do_install_scans_with_resolved_identifier(monkeypatch, tmp_path, hub_env):
    import tools.skills_guard as guard
    import tools.skills_hub as hub

    canonical_identifier = "skills-sh/anthropics/skills/frontend-design"

    class _ResolvedSource:
        def source_id(self):
            return "skills-sh"

        def trust_level_for(self, _identifier):
            return "trusted"

        def inspect(self, identifier):
            return type(
                "Meta",
                (),
                {
                    "extra": {},
                    "identifier": canonical_identifier,
                },
            )()

        def fetch(self, identifier):
            return type(
                "Bundle",
                (),
                {
                    "name": "frontend-design",
                    "files": {"SKILL.md": "# Frontend Design"},
                    "source": "skills.sh",
                    "identifier": canonical_identifier,
                    "trust_level": "trusted",
                    "metadata": {},
                },
            )()

    q_path = tmp_path / "skills" / ".hub" / "quarantine" / "frontend-design"
    q_path.mkdir(parents=True)
    (q_path / "SKILL.md").write_text("# Frontend Design")

    scanned = {}

    def _scan_skill(skill_path, source="community"):
        scanned["source"] = source
        return guard.ScanResult(
            skill_name="frontend-design",
            source=source,
            trust_level="trusted",
            verdict="safe",
        )

    monkeypatch.setattr(hub, "ensure_hub_dirs", lambda: None)
    monkeypatch.setattr(hub, "create_source_router", lambda auth: [_ResolvedSource()])
    monkeypatch.setattr(hub, "quarantine_bundle", lambda bundle: q_path)
    monkeypatch.setattr(
        hub,
        "HubLockFile",
        lambda: type("Lock", (), {"get_installed": lambda self, name: None})(),
    )
    monkeypatch.setattr(
        hub,
        "scan_skill_with_authority",
        lambda skill_path, authority: _scan_skill(
            skill_path,
            source=authority.scan_source,
        ),
    )
    monkeypatch.setattr(guard, "format_scan_report", lambda result: "scan ok")
    monkeypatch.setattr(
        guard,
        "should_allow_install",
        lambda result, force=False: (False, "stop after scan"),
    )

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)

    do_install(
        "skils-sh/anthropics/skills/frontend-design", console=console, skip_confirm=True
    )

    assert scanned["source"] == f"hub-adapter:unverified:{canonical_identifier}"


def test_do_install_scans_official_bundles_with_source_provenance(
    monkeypatch, tmp_path, hub_env
):
    import tools.skills_guard as guard
    import tools.skills_hub as hub

    official_source = hub.OptionalSkillSource()
    official_source.inspect = lambda _identifier: type(
        "Meta",
        (),
        {
            "extra": {},
            "identifier": "official/agent/prunus-gaia",
        },
    )()
    official_source.fetch = lambda _identifier: type(
        "Bundle",
        (),
        {
            "name": "prunus-gaia",
            "files": {"SKILL.md": "# Prunus Gaia"},
            "source": "official",
            "identifier": "official/agent/prunus-gaia",
            "trust_level": "builtin",
            "metadata": {},
        },
    )()

    q_path = tmp_path / "skills" / ".hub" / "quarantine" / "prunus-gaia"
    q_path.mkdir(parents=True)
    (q_path / "SKILL.md").write_text("# Prunus Gaia")

    scanned = {}

    def _scan_skill(skill_path, source="community"):
        scanned["source"] = source
        return guard.ScanResult(
            skill_name="prunus-gaia",
            source=source,
            trust_level="builtin",
            verdict="safe",
        )

    monkeypatch.setattr(hub, "ensure_hub_dirs", lambda: None)
    monkeypatch.setattr(hub, "create_source_router", lambda auth: [official_source])
    monkeypatch.setattr(hub, "quarantine_bundle", lambda bundle: q_path)
    monkeypatch.setattr(
        hub,
        "HubLockFile",
        lambda: type("Lock", (), {"get_installed": lambda self, name: None})(),
    )
    monkeypatch.setattr(
        hub,
        "scan_skill_with_authority",
        lambda skill_path, authority: _scan_skill(
            skill_path,
            source=authority.scan_source,
        ),
    )
    monkeypatch.setattr(guard, "format_scan_report", lambda result: "scan ok")
    monkeypatch.setattr(
        guard,
        "should_allow_install",
        lambda result, force=False: (False, "stop after scan"),
    )

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)

    do_install("official/agent/prunus-gaia", console=console, skip_confirm=True)

    assert scanned["source"] == ("hub-adapter:official:official/agent/prunus-gaia")


def test_virtual_official_source_gets_community_consent_ui(
    monkeypatch, tmp_path, hub_env
):
    import tools.skills_guard as guard
    import tools.skills_hub as hub

    class VirtualOfficial:
        def source_id(self):
            return "official"

        def inspect(self, identifier):
            return type(
                "Meta",
                (),
                {"extra": {}, "identifier": identifier},
            )()

        def fetch(self, identifier):
            return hub.SkillBundle(
                name="spoofed-official",
                files={"SKILL.md": "# community bytes\n"},
                source="official",
                identifier=identifier,
                trust_level="builtin",
            )

    q_path = tmp_path / "skills" / ".hub" / "quarantine" / "spoofed"
    q_path.mkdir(parents=True)
    (q_path / "SKILL.md").write_text("# community bytes\n")
    monkeypatch.setattr(hub, "ensure_hub_dirs", lambda: None)
    monkeypatch.setattr(hub, "create_source_router", lambda auth: [VirtualOfficial()])
    monkeypatch.setattr(hub, "quarantine_bundle", lambda bundle: q_path)
    monkeypatch.setattr(
        hub,
        "HubLockFile",
        lambda: type("Lock", (), {"get_installed": lambda self, name: None})(),
    )
    monkeypatch.setattr(
        hub,
        "scan_skill_with_authority",
        lambda _path, authority: guard.ScanResult(
            skill_name="spoofed-official",
            source=authority.scan_source,
            trust_level=authority.trust_level,
            verdict="safe",
        ),
    )
    monkeypatch.setattr(guard, "format_scan_report", lambda _result: "scan ok")
    monkeypatch.setattr(
        guard,
        "should_allow_install",
        lambda _result, force=False: (True, "ok"),
    )
    monkeypatch.setattr(
        "fabric_cli.skills_hub.display_fabric_home",
        lambda: "/profile",
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    sink = StringIO()

    outcome = do_install(
        "official/category/spoofed-official",
        console=Console(file=sink, force_terminal=False, color_system=None),
    )

    output = sink.getvalue()
    assert outcome.installed is False
    assert "third-party skill" in output
    assert "official optional skill maintained" not in output
    assert "/profile/skills/spoofed-official/" in output


def test_do_install_preserves_nested_official_optional_path(
    monkeypatch, tmp_path, hub_env
):
    import tools.skills_hub as hub

    def official_nested_source():
        source = hub.OptionalSkillSource()
        source.inspect = lambda _identifier: type(
            "Meta",
            (),
            {
                "extra": {},
                "identifier": "official/mlops/training/trl-fine-tuning",
            },
        )()
        source.fetch = lambda _identifier: type(
            "Bundle",
            (),
            {
                "name": "trl-fine-tuning",
                "files": {"SKILL.md": "# TRL"},
                "source": "official",
                "identifier": "official/mlops/training/trl-fine-tuning",
                "trust_level": "builtin",
                "metadata": {},
            },
        )()
        return source

    installs = _install_mocks(monkeypatch, tmp_path, official_nested_source)

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    do_install(
        "official/mlops/training/trl-fine-tuning",
        console=console,
        skip_confirm=True,
    )

    assert installs == [{"name": "trl-fine-tuning", "category": "mlops/training"}]


# ---------------------------------------------------------------------------
# UrlSource-specific install paths: --name override, interactive prompts,
# non-interactive error, existing-category scan.
# ---------------------------------------------------------------------------


def _make_url_bundle_fetcher(
    name="", awaiting_name=True, url="https://example.com/SKILL.md"
):
    """Return a fake source that simulates ``UrlSource.fetch`` for a
    URL-sourced skill whose name hasn't been auto-resolved."""
    import tools.skills_hub as hub

    class _UrlSource(hub.UrlSource):
        def inspect(self, identifier):
            return type(
                "Meta",
                (),
                {
                    "extra": {"url": url, "awaiting_name": awaiting_name},
                    "identifier": url,
                    "name": name,
                    "path": name,
                },
            )()

        def fetch(self, identifier):
            return type(
                "Bundle",
                (),
                {
                    "name": name,
                    "files": {"SKILL.md": "---\ndescription: ok\n---\n# body\n"},
                    "source": "url",
                    "identifier": url,
                    "trust_level": "community",
                    "metadata": {"url": url, "awaiting_name": awaiting_name},
                },
            )()

    return _UrlSource


def _install_mocks(monkeypatch, tmp_path, source_factory, category_hint=""):
    """Wire the minimum set of monkeypatches for a do_install dry run."""
    import tools.skills_hub as hub
    import tools.skills_guard as guard

    q_path = tmp_path / "skills" / ".hub" / "quarantine" / "pending"
    q_path.mkdir(parents=True)

    install_calls: list = []

    def _install_from_quarantine(
        q,
        name,
        category,
        bundle,
        result,
        *,
        source_authority=None,
        force=False,
    ):
        from tools.skills_hub import HubMutationOutcome

        install_calls.append({"name": name, "category": category})
        install_dir = tmp_path / "skills" / (f"{category}/" if category else "") / name
        install_dir.mkdir(parents=True, exist_ok=True)
        return HubMutationOutcome(
            status="committed",
            message="installed",
            install_path=install_dir,
        )

    monkeypatch.setattr(hub, "ensure_hub_dirs", lambda: None)
    monkeypatch.setattr(hub, "create_source_router", lambda auth: [source_factory()])
    monkeypatch.setattr(hub, "quarantine_bundle", lambda bundle: q_path)
    monkeypatch.setattr(hub, "install_from_quarantine", _install_from_quarantine)
    monkeypatch.setattr(
        hub,
        "HubLockFile",
        lambda: type("Lock", (), {"get_installed": lambda self, n: None})(),
    )
    monkeypatch.setattr(
        hub,
        "scan_skill_with_authority",
        lambda skill_path, authority: guard.ScanResult(
            skill_name="pending",
            source=authority.scan_source,
            trust_level=authority.trust_level,
            verdict="safe",
        ),
    )
    monkeypatch.setattr(guard, "format_scan_report", lambda result: "scan ok")
    monkeypatch.setattr(
        guard, "should_allow_install", lambda result, force=False: (True, "ok")
    )
    return install_calls


def test_url_install_uses_name_override_on_non_interactive_surface(
    monkeypatch, tmp_path, hub_env
):
    installs = _install_mocks(monkeypatch, tmp_path, _make_url_bundle_fetcher())

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    outcome = do_install(
        "https://example.com/SKILL.md",
        console=console,
        skip_confirm=True,
        name_override="my-url-skill",
    )

    assert installs == [{"name": "my-url-skill", "category": ""}]
    assert outcome.installed is True
    assert outcome.name == "my-url-skill"


def test_snapshot_install_refuses_changed_digest_before_commit(
    monkeypatch, tmp_path, hub_env
):
    import tools.skills_hub as hub

    url = "https://example.com/exact/SKILL.md"
    virtual_source = _make_url_bundle_fetcher(
        name="exact",
        awaiting_name=False,
        url=url,
    )()
    exact_source = hub.UrlSource()
    exact_source.inspect = virtual_source.inspect
    exact_source.fetch = virtual_source.fetch
    installs = _install_mocks(
        monkeypatch,
        tmp_path,
        lambda: exact_source,
    )
    identity = {
        "name": "exact",
        "source_name": "exact",
        "source_revision": url,
        "authority": {
            "adapter": "url",
            "remote_identifier": url,
            "bundle_source": "url",
            "trust_level": "community",
        },
        "digest": "a" * 64,
        "category": "",
    }

    outcome = do_install(
        url,
        console=Console(file=StringIO(), force_terminal=False, color_system=None),
        skip_confirm=True,
        snapshot_identity=identity,
    )

    assert outcome.installed is False
    assert "digest" in outcome.message
    assert installs == []


def test_do_install_refuses_untracked_local_destination_before_quarantine(
    monkeypatch, tmp_path, hub_env
):
    installs = _install_mocks(
        monkeypatch,
        tmp_path,
        _make_url_bundle_fetcher(name="local-skill", awaiting_name=False),
    )
    local = tmp_path / "skills" / "local-skill"
    local.mkdir(parents=True)
    sentinel = local / "SKILL.md"
    sentinel.write_text("# User local bytes\n")

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    outcome = do_install(
        "https://example.com/local-skill/SKILL.md",
        console=console,
        skip_confirm=True,
    )

    assert outcome.installed is False
    assert "untracked or locally owned" in outcome.message
    assert sentinel.read_text() == "# User local bytes\n"
    assert installs == []


def test_url_install_rejects_invalid_name_override(monkeypatch, tmp_path, hub_env):
    installs = _install_mocks(monkeypatch, tmp_path, _make_url_bundle_fetcher())

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    outcome = do_install(
        "https://example.com/SKILL.md",
        console=console,
        skip_confirm=True,
        name_override="SKILL",  # rejected by _is_valid_installed_skill_name
    )

    assert installs == []  # did NOT install
    assert outcome.installed is False
    assert "Invalid skill name override" in outcome.message
    assert "Invalid --name" in sink.getvalue()


def test_url_install_actionable_error_on_non_interactive_with_no_name(
    monkeypatch, tmp_path, hub_env
):
    installs = _install_mocks(monkeypatch, tmp_path, _make_url_bundle_fetcher())

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    do_install(
        "https://example.com/SKILL.md",
        console=console,
        skip_confirm=True,
        # No name_override — should error out with a retry hint.
    )

    assert installs == []
    out = sink.getvalue()
    assert "Cannot install from URL" in out
    assert "--name <your-name>" in out


def test_url_install_prompts_interactively_when_tty(monkeypatch, tmp_path, hub_env):
    installs = _install_mocks(monkeypatch, tmp_path, _make_url_bundle_fetcher())

    # Simulate user typing "my-interactive" to name prompt, then "" to category.
    answers = iter(["my-interactive", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    do_install(
        "https://example.com/SKILL.md",
        console=console,
        skip_confirm=False,  # interactive
        force=True,  # skip the final confirm prompt (tested elsewhere)
    )

    assert installs == [{"name": "my-interactive", "category": ""}]


def test_url_install_prompts_category_and_uses_typed_value(
    monkeypatch, tmp_path, hub_env
):
    import tools.skills_hub as hub

    installs = _install_mocks(
        monkeypatch,
        tmp_path,
        _make_url_bundle_fetcher(name="sharethis-chat", awaiting_name=False),
    )

    # Stage an existing category bucket so _existing_categories finds it.
    (hub.SKILLS_DIR / "productivity" / "notion").mkdir(parents=True)
    (hub.SKILLS_DIR / "productivity" / "notion" / "SKILL.md").write_text("# notion")

    # Name is already resolved (from frontmatter) → only category prompt fires.
    answers = iter(["productivity"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    do_install(
        "https://example.com/sharethis-chat/SKILL.md",
        console=console,
        skip_confirm=False,
        force=True,
    )

    assert installs == [{"name": "sharethis-chat", "category": "productivity"}]
    assert "Existing: productivity" in sink.getvalue()


def test_url_install_cancel_name_prompt_aborts(monkeypatch, tmp_path, hub_env):
    installs = _install_mocks(monkeypatch, tmp_path, _make_url_bundle_fetcher())

    # Empty input with no default → name prompt returns None → abort.
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None)
    do_install(
        "https://example.com/SKILL.md",
        console=console,
        skip_confirm=False,
        force=True,
    )

    assert installs == []
    assert "Installation cancelled" in sink.getvalue()


def test_snapshot_export_uses_running_fabric_version(monkeypatch, tmp_path, hub_env):
    import fabric_cli
    import tools.skills_hub as hub

    monkeypatch.setattr(fabric_cli, "__version__", "9.8.7")

    class _SnapshotLock:
        def __init__(self, path=None):
            self.path = path

        def list_installed(self):
            return []

        def load(self, *, strict=False):
            return {"version": 1, "installed": {}}

        def save(self, data):
            self.path.write_text(json.dumps(data), encoding="utf-8")

        def ensure_parent_durable(self):
            return None

    monkeypatch.setattr(hub, "HubLockFile", _SnapshotLock)
    monkeypatch.setattr(
        hub,
        "TapsManager",
        lambda: type("Taps", (), {"load": lambda self, strict=False: []})(),
    )
    output = tmp_path / "skills-snapshot.json"

    do_snapshot_export(str(output))

    snapshot = json.loads(output.read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == 2
    assert snapshot["fabric_version"] == "9.8.7"


def test_snapshot_export_is_one_locked_point_in_time(monkeypatch, tmp_path, hub_env):
    import fabric_cli.skills_hub as cli_hub
    import tools.skills_hub as hub

    monkeypatch.setattr(cli_hub, "get_fabric_home", lambda: tmp_path)
    manager = hub.TapsManager()
    assert manager.add("before/repo").committed
    real_load = hub.HubLockFile.load
    export_holds_lock = threading.Event()
    release_export = threading.Event()

    def paused_load(self, *, strict=False):
        result = real_load(self, strict=strict)
        if threading.current_thread().name == "snapshot-export":
            export_holds_lock.set()
            assert release_export.wait(timeout=5)
        return result

    monkeypatch.setattr(hub.HubLockFile, "load", paused_load)
    output = tmp_path / "snapshot.json"
    export_thread = threading.Thread(
        name="snapshot-export",
        target=lambda: do_snapshot_export(str(output)),
    )
    writer_thread = threading.Thread(
        name="tap-writer",
        target=lambda: manager.add("after/repo"),
    )
    export_thread.start()
    assert export_holds_lock.wait(timeout=5)
    writer_thread.start()
    writer_thread.join(timeout=0.1)
    assert writer_thread.is_alive()
    release_export.set()
    export_thread.join(timeout=5)
    writer_thread.join(timeout=5)

    exported = json.loads(output.read_text(encoding="utf-8"))
    assert [tap["repo"] for tap in exported["taps"]] == ["before/repo"]
    assert {tap["repo"] for tap in manager.load()} == {
        "before/repo",
        "after/repo",
    }


# ── _existing_categories ────────────────────────────────────────────────────


def test_existing_categories_skips_top_level_skills(monkeypatch, tmp_path, hub_env):
    import tools.skills_hub as hub
    from fabric_cli.skills_hub import _existing_categories

    # Category bucket with nested skill.
    (hub.SKILLS_DIR / "productivity" / "notion").mkdir(parents=True)
    (hub.SKILLS_DIR / "productivity" / "notion" / "SKILL.md").write_text("# notion")

    # Flat skill at top level (NOT a category).
    (hub.SKILLS_DIR / "my-flat-skill").mkdir()
    (hub.SKILLS_DIR / "my-flat-skill" / "SKILL.md").write_text("# flat")

    # Empty dir (NOT a category — no SKILL.md below).
    (hub.SKILLS_DIR / "empty-dir").mkdir()

    # Hidden dir (ignored).
    (hub.SKILLS_DIR / ".hub").mkdir(exist_ok=True)

    cats = _existing_categories()
    assert cats == ["productivity"]


def test_existing_categories_returns_empty_when_skills_dir_missing(monkeypatch, tmp_path, hub_env):
    # hub_env creates tmp_path/skills/.hub — we point SKILLS_DIR at a missing sibling.
    import tools.skills_hub as hub
    monkeypatch.setattr(hub, "SKILLS_DIR", tmp_path / "does-not-exist")

    from fabric_cli.skills_hub import _existing_categories
    assert _existing_categories() == []


# ---------------------------------------------------------------------------
# browse_skills — dedup by identifier, not name
# ---------------------------------------------------------------------------


def test_browse_skills_dedup_uses_identifier_not_name(monkeypatch):
    """browse_skills() must not collapse browse-sh skills that share a task name.

    Airbnb and Booking.com both publish a 'search-listings' skill. Before the
    fix, both were keyed by name so only one survived deduplication. After the
    fix, each unique identifier produces a distinct result.
    """
    from tools.skills_hub import SkillMeta
    from fabric_cli.skills_hub import browse_skills

    airbnb = SkillMeta(
        name="search-listings", description="Airbnb search", source="browse-sh",
        identifier="browse-sh/airbnb.com/search-listings-ddgioa", trust_level="community",
    )
    booking = SkillMeta(
        name="search-listings", description="Booking.com search", source="browse-sh",
        identifier="browse-sh/booking.com/search-listings-xyzab", trust_level="community",
    )

    mock_src = type("S", (), {
        "source_id": lambda self: "browse-sh",
        "search": lambda self, q, limit=500: [airbnb, booking],
    })()

    # browse_skills() imports create_source_router locally from tools.skills_hub,
    # so the patch must target the source module, not fabric_cli.skills_hub.
    with patch("tools.skills_hub.create_source_router", return_value=[mock_src]):
        result = browse_skills(page=1, page_size=50)

    names = [item["name"] for item in result["items"]]
    assert names.count("search-listings") == 2, (
        "browse_skills() must not deduplicate browse-sh skills with the same name "
        "but different identifiers"
    )


def test_do_browse_reports_live_per_source_progress():
    """do_browse must pass an on_source_done callback so the status line ticks
    off each source as it resolves, instead of showing a frozen spinner while
    a slow source blocks. The page is still rendered once, after the full
    result set is merged and trust-sorted."""
    from fabric_cli.skills_hub import do_browse
    from tools.skills_hub import SkillMeta

    meta = SkillMeta(
        name="demo", description="d", source="official",
        identifier="official/demo", trust_level="builtin",
    )

    captured = {}

    def fake_parallel(sources, query="", per_source_limits=None,
                      source_filter="all", overall_timeout=30,
                      on_source_done=None):
        # Simulate two sources completing — the callback must be wired through.
        assert on_source_done is not None, "do_browse must pass on_source_done"
        on_source_done("official", 1)
        on_source_done("clawhub", 0)
        captured["called"] = True
        return [meta], {"official": 1, "clawhub": 0}, []

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None, width=120)

    with patch("tools.skills_hub.create_source_router", return_value=[]), \
         patch("tools.skills_hub.GitHubAuth"), \
         patch("tools.skills_hub.parallel_search_sources", side_effect=fake_parallel):
        do_browse(page=1, page_size=20, console=console)

    assert captured.get("called"), "parallel_search_sources was not invoked"
    # The rendered page still shows the (single) merged result.
    assert "demo" in sink.getvalue()


def test_do_browse_neutralizes_nous_provenance_by_default(monkeypatch):
    from fabric_cli.skills_hub import browse_skills, do_browse
    from tools.skills_hub import SkillMeta

    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.delenv("FABRIC_MODEL_PROVIDERS", raising=False)
    meta = SkillMeta(
        name="demo",
        description="Nous Research made Fabric",
        source="official",
        identifier="official/demo",
        trust_level="builtin",
    )

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None, width=160)
    with patch("tools.skills_hub.create_source_router", return_value=[]), \
         patch("tools.skills_hub.GitHubAuth"), \
         patch(
             "tools.skills_hub.parallel_search_sources",
             return_value=([meta], {"official": 1}, []),
         ):
        do_browse(page=1, page_size=20, console=console)
        api_result = browse_skills(page=1, page_size=20)

    output = sink.getvalue()
    assert "bundled optional skill(s)" in output
    assert "upstream maintainers" in output
    assert "made Fabric" in output
    assert "Nous" not in output
    assert "Hermes" not in output
    assert api_result["items"][0]["description"] == "the upstream maintainers made Fabric"
    assert api_result["items"][0]["source"] == "official"
    assert api_result["items"][0]["trust"] == "bundled"


def test_do_browse_restores_nous_provenance_under_explicit_opt_in(monkeypatch):
    from fabric_cli.skills_hub import browse_skills, do_browse
    from tools.skills_hub import SkillMeta

    monkeypatch.delenv("FABRIC_CAPABILITY_CATALOG", raising=False)
    monkeypatch.setenv("FABRIC_MODEL_PROVIDERS", "openai-api,nous")
    meta = SkillMeta(
        name="demo",
        description="Nous Research made Fabric",
        source="official",
        identifier="official/demo",
        trust_level="builtin",
    )

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None, width=160)
    with patch("tools.skills_hub.create_source_router", return_value=[]), \
         patch("tools.skills_hub.GitHubAuth"), \
         patch(
             "tools.skills_hub.parallel_search_sources",
             return_value=([meta], {"official": 1}, []),
         ):
        do_browse(page=1, page_size=20, console=console)
        api_result = browse_skills(page=1, page_size=20)

    output = sink.getvalue()
    assert "official optional skill(s) from Nous Research" in output
    assert "Nous Research made Fabric" in output
    assert api_result["items"][0]["description"] == "Nous Research made Fabric"
    assert api_result["items"][0]["source"] == "official"
    assert api_result["items"][0]["trust"] == "official"


# ---------------------------------------------------------------------------
# Regression: full identifier must be recoverable from `fabric skills search`
# even when the slug is too long to fit the terminal width (issue #33674).
# ---------------------------------------------------------------------------

# A real browse-sh-style slug whose trailing -XXXXXX hash matters for install
_LONG_SLUG = "browse-sh/weather.gov/get-forecast-1uezib"

_LONG_RESULT = type("R", (), {
    "name": "get-forecast",
    "description": "Fetch the forecast",
    "source": "browse-sh",
    "trust_level": "community",
    "identifier": _LONG_SLUG,
})()


def test_do_search_identifier_column_does_not_truncate_long_slug():
    """The Identifier column must use overflow='fold', not the default ellipsis.

    Renders into a deliberately narrow Console; the full slug (including the
    trailing -1uezib hash) must still appear in the output. Before the fix,
    Rich would render `browse-sh/weather…` and lose the hash.
    """
    from fabric_cli.skills_hub import do_search

    sink = StringIO()
    # Narrow width forces Rich to apply overflow rules — exactly the scenario
    # the issue reports. width=40 is too small for the slug; we want the slug
    # wrapped (not ellipsis-truncated).
    console = Console(file=sink, force_terminal=False, color_system=None, width=40)

    with patch("tools.skills_hub.unified_search", return_value=[_LONG_RESULT]), \
         patch("tools.skills_hub.create_source_router", return_value={}), \
         patch("tools.skills_hub.GitHubAuth"):
        do_search("weather", console=console)

    output = sink.getvalue()

    # The fix is working when the Identifier column wraps the slug across
    # multiple lines (folded chunks) rather than emitting ONE line with an
    # ellipsis. Extract every chunk that appears in the rightmost cell of
    # the table by walking lines that look like table rows ("│ ... │") and
    # taking the last `│...│` cell. Concatenating those chunks must yield
    # the full slug.
    chunks = []
    for line in output.splitlines():
        # Table data rows start and end with the box-drawing vertical bar.
        if not line.startswith("│") or not line.rstrip().endswith("│"):
            continue
        # Last `│ ... │` cell on the row is the Identifier column.
        last_cell = line.rstrip().rsplit("│", 2)[-2].strip()
        if last_cell:
            chunks.append(last_cell)
    reconstructed = "".join(chunks)
    assert _LONG_SLUG in reconstructed, (
        f"Expected full slug {_LONG_SLUG!r} to be recoverable from the "
        f"folded Identifier column; got chunks {chunks!r}\n"
        f"Full output:\n{output}"
    )
    # And the truncating ellipsis must NOT appear in the Identifier column.
    # Rich uses U+2026 HORIZONTAL ELLIPSIS for the default overflow="ellipsis".
    assert "\u2026" not in reconstructed, (
        f"Identifier column still ellipsis-truncated: {reconstructed!r}"
    )


def test_do_search_json_flag_emits_full_identifiers(capsys):
    """`--json` must print a parseable array with full identifiers and skip the table."""
    from fabric_cli.skills_hub import do_search

    sink = StringIO()
    console = Console(file=sink, force_terminal=False, color_system=None, width=40)

    with patch("tools.skills_hub.unified_search", return_value=[_LONG_RESULT]), \
         patch("tools.skills_hub.create_source_router", return_value={}), \
         patch("tools.skills_hub.GitHubAuth"):
        do_search("weather", console=console, as_json=True)

    # JSON goes to stdout via print(), not the Rich console sink.
    captured = capsys.readouterr().out
    import json as _json
    payload = _json.loads(captured)
    assert isinstance(payload, list) and len(payload) == 1
    assert payload[0]["identifier"] == _LONG_SLUG
    assert payload[0]["name"] == "get-forecast"
    assert payload[0]["source"] == "browse-sh"
    # Table render must be suppressed — sink should be empty (no "Searching for:" header).
    assert "Searching for:" not in sink.getvalue()
