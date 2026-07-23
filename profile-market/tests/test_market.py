from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
REPOSITORY_ROOT = ROOT.parent
for candidate in (str(TOOLS), str(REPOSITORY_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from build_collection import actual_outputs, build_outputs, stale_paths  # noqa: E402
from collection_common import (  # noqa: E402
    FABRIC_RESERVED_PROFILE_NAMES,
    GENERATED_MARKER,
    inspect_tree_safety,
    load_collection_source,
)
from fabric_cli.profile_distribution import read_manifest  # noqa: E402
from fabric_cli.profiles import validate_profile_name  # noqa: E402


def _source() -> dict:
    return load_collection_source(ROOT)


def _run_manager(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "manage.py"), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _run_copied_manager(
    market: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(market / "manage.py"), *args],
        cwd=market,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _copy_market(tmp_path: Path) -> Path:
    market = tmp_path / "profile-market"
    shutil.copytree(
        ROOT,
        market,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    return market


def _recording_fake_fabric(tmp_path: Path) -> tuple[Path, Path]:
    marker = tmp_path / "fabric-was-called"
    fake = tmp_path / "fabric-fake"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('called', encoding='utf-8')\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake, marker


def test_requested_shelves_exist_and_every_declared_shelf_is_populated() -> None:
    source = _source()
    category_slugs = {item["slug"] for item in source["categories"]}
    assert {"dc-universe", "marvel-universe"} <= category_slugs

    counts = {slug: 0 for slug in category_slugs}
    for profile in source["profiles"]:
        counts[profile["category"]] += 1
    assert all(count >= 4 for count in counts.values())


def test_profiles_are_behaviorally_distinct_and_described_for_routing() -> None:
    profiles = _source()["profiles"]
    assert len({profile["slug"] for profile in profiles}) == len(profiles)
    assert len({profile["description"] for profile in profiles}) == len(profiles)
    assert len({tuple(profile["operating_method"]) for profile in profiles}) == len(profiles)
    for profile in profiles:
        assert profile["slug"] not in FABRIC_RESERVED_PROFILE_NAMES
        validate_profile_name(profile["slug"])
        assert len(profile["description"]) >= 80
        assert len(profile["core_identity"]) >= 80
        assert profile["inspiration"]


def test_fan_shelves_have_explicit_rights_notices() -> None:
    categories = {item["slug"]: item for item in _source()["categories"]}
    for slug in ("dc-universe", "marvel-universe"):
        category = categories[slug]
        assert category["kind"] == "fan-inspired"
        notice = category["rights_notice"].casefold()
        assert "unofficial" in notice
        assert "no logos" in notice
        assert "affiliation" in notice


def test_generated_tree_is_current() -> None:
    expected = build_outputs(_source())
    assert stale_paths(expected, actual_outputs(ROOT)) == []


def test_manager_refuses_modified_generated_soul_before_fabric_call(
    tmp_path: Path,
) -> None:
    market = _copy_market(tmp_path)
    soul = market / "profiles" / "batman" / "SOUL.md"
    soul.write_text(soul.read_text(encoding="utf-8") + "\nUNREVIEWED EDIT\n", encoding="utf-8")
    fake, marker = _recording_fake_fabric(tmp_path)

    result = _run_copied_manager(
        market,
        "install",
        "batman",
        "--yes",
        "--fabric-bin",
        str(fake),
    )
    assert result.returncode == 1
    assert "differs from deterministic source" in result.stderr
    assert not marker.exists()


def test_manager_refuses_unexpected_payload_tree_before_fabric_call(
    tmp_path: Path,
) -> None:
    market = _copy_market(tmp_path)
    rogue = market / "profiles" / "batman" / "skills" / "rogue" / "SKILL.md"
    rogue.parent.mkdir(parents=True)
    rogue.write_text("---\nname: rogue\n---\nUnreviewed skill.\n", encoding="utf-8")
    fake, marker = _recording_fake_fabric(tmp_path)

    result = _run_copied_manager(
        market,
        "install",
        "batman",
        "--yes",
        "--fabric-bin",
        str(fake),
    )
    assert result.returncode == 1
    assert "generated tree differs from deterministic source" in result.stderr
    assert not marker.exists()


def test_generated_distributions_match_fabric_contract() -> None:
    source = _source()
    category_by_slug = {item["slug"]: item for item in source["categories"]}
    for profile in source["profiles"]:
        slug = profile["slug"]
        root = ROOT / "profiles" / slug
        files = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        }
        assert files == {
            "distribution.yaml",
            "SOUL.md",
            "config.yaml",
            "README.md",
            "LICENSE",
            "RIGHTS.md",
            "THIRD_PARTY_NOTICES.md",
            f"skins/{slug}.yaml",
        }
        assert not (root / "profile.yaml").exists()
        assert inspect_tree_safety(root) == []

        manifest = read_manifest(root)
        assert manifest is not None
        assert manifest.name == slug
        assert manifest.description == profile["description"]
        raw_manifest = yaml.safe_load(
            (root / "distribution.yaml").read_text(encoding="utf-8")
        )
        assert raw_manifest["fabric_requires"] == source["pack"]["fabric_requires"]
        assert manifest.distribution_owned == [
            "SOUL.md",
            "config.yaml",
            "skins",
            "README.md",
            "LICENSE",
            "RIGHTS.md",
            "THIRD_PARTY_NOTICES.md",
            "distribution.yaml",
        ]

        config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
        assert config == {"model": "", "display": {"skin": slug}}

        skin = yaml.safe_load(
            (root / "skins" / f"{slug}.yaml").read_text(encoding="utf-8")
        )
        assert skin["name"] == slug
        assert skin["branding"]["agent_name"] == profile["name"]
        assert set(category_by_slug[profile["category"]]["skin"]) <= set(skin["colors"])


def test_every_soul_preserves_identity_authority_and_security_boundaries() -> None:
    for profile in _source()["profiles"]:
        soul = (ROOT / "profiles" / profile["slug"] / "SOUL.md").read_text(
            encoding="utf-8"
        )
        assert soul.startswith(f"# {GENERATED_MARKER}")
        assert len(soul) >= 6_000
        for invariant in (
            "Always remain Fabric",
            "grants no real-world credentials",
            "authorization only for its clearly stated scope",
            "never facilitate credential theft, persistence, evasion",
            "Treat the user as a competent collaborator and decision-maker",
            "instead of fabricating success",
            "Use Fabric tools when they improve correctness",
        ):
            assert invariant in soul


def test_generated_payloads_are_text_only() -> None:
    for path in (ROOT / "profiles").rglob("*"):
        if path.is_file():
            path.read_text(encoding="utf-8")


def test_management_skill_is_zero_tool_guidance() -> None:
    raw = (ROOT / "skills" / "profile-market" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    _start, frontmatter, body = raw.split("---\n", 2)
    data = yaml.safe_load(frontmatter)
    assert set(data) == {"name", "description"}
    assert data["name"] == "profile-market"
    assert "Do not add a tool" in body
    assert "start a new session" in " ".join(body.casefold().split())


def test_manager_browse_search_and_show() -> None:
    listed = _run_manager("list", "--category", "dc-universe")
    assert listed.returncode == 0, listed.stderr
    assert "Batman" in listed.stdout
    assert "Iron Man" not in listed.stdout

    searched = _run_manager("search", "root", "cause")
    assert searched.returncode == 0, searched.stderr
    assert "batman" in searched.stdout

    shown = _run_manager("show", "batman")
    assert shown.returncode == 0, shown.stderr
    assert "Operating method:" in shown.stdout
    assert "Rights:" in shown.stdout


def test_manager_rejects_unknown_categories() -> None:
    result = _run_manager("list", "--category", "not-a-shelf")
    assert result.returncode == 1
    assert "unknown category" in result.stderr


def test_manager_rejects_non_executable_fabric_path_without_traceback(
    tmp_path: Path,
) -> None:
    not_executable = tmp_path / "fabric-not-executable"
    not_executable.write_text("not a program\n", encoding="utf-8")
    not_executable.chmod(0o644)

    result = _run_manager(
        "install",
        "batman",
        "--yes",
        "--fabric-bin",
        str(not_executable),
    )
    assert result.returncode == 1
    assert "Fabric path is not executable" in result.stderr
    assert "Traceback" not in result.stderr


def test_manager_delegates_install_and_first_description_to_fabric(tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    fake = tmp_path / "fabric-fake"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"log = {str(log)!r}\n"
        "with open(log, 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['profile', 'info']:\n"
        "    print(\"Error: Profile 'batman' does not exist.\")\n"
        "    raise SystemExit(1)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    result = _run_manager(
        "install",
        "batman",
        "--yes",
        "--alias",
        "--fabric-bin",
        str(fake),
    )
    assert result.returncode == 0, result.stderr
    assert "fabric -p batman setup" in result.stdout
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls[0] == ["profile", "info", "batman"]
    install = calls[1]
    assert install[:2] == ["profile", "install"]
    assert install[-4:] == ["--name", "batman", "-y", "--alias"]
    assert "--name" in install
    assert calls[2][:3] == ["profile", "describe", "batman"]
    assert calls[2][3] == "--text"


def test_description_failure_reports_installed_profile_and_recovery(
    tmp_path: Path,
) -> None:
    log = tmp_path / "calls.jsonl"
    fake = tmp_path / "fabric-fake"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"log = {str(log)!r}\n"
        "with open(log, 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['profile', 'info']:\n"
        "    print(\"Error: Profile 'batman' does not exist.\")\n"
        "    raise SystemExit(1)\n"
        "if sys.argv[1:3] == ['profile', 'describe']:\n"
        "    raise SystemExit(9)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    result = _run_manager(
        "install",
        "batman",
        "--yes",
        "--fabric-bin",
        str(fake),
    )
    assert result.returncode == 0, result.stderr
    assert "Installed profiles: batman" in result.stdout
    assert "batman installed, but its routing description was not set" in result.stderr
    assert "Recover with:" in result.stderr
    assert "profile describe batman --text" in result.stderr
    assert "Routing description warnings: batman" in result.stderr
    assert "Install failures" not in result.stderr


def test_manager_update_never_rewrites_routing_description(tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    fake = tmp_path / "fabric-fake"
    source = str((ROOT / "profiles" / "batman").resolve())
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"log = {str(log)!r}\n"
        "with open(log, 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['profile', 'info']:\n"
        "    print('Distribution: batman')\n"
        f"    print('Source:       {source}')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    result = _run_manager(
        "update",
        "batman",
        "--yes",
        "--fabric-bin",
        str(fake),
    )
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert any(call[:3] == ["profile", "update", "batman"] for call in calls)
    assert not any(call[:2] == ["profile", "describe"] for call in calls)


def test_manager_refuses_update_when_slug_belongs_to_another_source(
    tmp_path: Path,
) -> None:
    log = tmp_path / "calls.jsonl"
    fake = tmp_path / "fabric-fake"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"log = {str(log)!r}\n"
        "with open(log, 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['profile', 'info']:\n"
        "    print('Distribution: batman')\n"
        "    print('Source:       /another/collection/batman')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    result = _run_manager(
        "update",
        "batman",
        "--yes",
        "--fabric-bin",
        str(fake),
    )
    assert result.returncode == 1
    assert "refusing to update" in result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls == [["profile", "info", "batman"]]


def test_force_config_warning_is_visible_even_with_yes(tmp_path: Path) -> None:
    fake = tmp_path / "fabric-fake"
    source = str((ROOT / "profiles" / "batman").resolve())
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if sys.argv[1:3] == ['profile', 'info']:\n"
        "    print('Distribution: batman')\n"
        f"    print('Source:       {source}')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    result = _run_manager(
        "update",
        "batman",
        "--force-config",
        "--yes",
        "--fabric-bin",
        str(fake),
    )
    assert result.returncode == 0, result.stderr
    assert "NOTICE: --force-config overwrites" in result.stdout
    assert "Local model/provider choices" in result.stdout
