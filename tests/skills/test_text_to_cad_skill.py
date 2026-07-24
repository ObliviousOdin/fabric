"""Hermetic tests for the text-to-cad skill's scripts and governance files.

The heavy CAD dependencies (build123d, numpy-stl, matplotlib) live only in
the skill's private venv, so these tests exercise the scripts' pure logic
and the governed contract — never geometry generation or the network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from agent.skill_contract import (
    source_freshness_blockers,
    validate_skill_directory,
)


SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "skills" / "creative" / "text-to-cad"
)


def load_script(name: str):
    path = SKILL_DIR / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        f"text_to_cad_{path.stem}_test", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_skill_directory_is_verified():
    validation = validate_skill_directory(SKILL_DIR, require_contract=True)
    assert validation.ok, [issue.message for issue in validation.errors]
    assert validation.status == "verified"


def test_skill_sources_are_fresh():
    validation = validate_skill_directory(SKILL_DIR, require_contract=True)
    assert source_freshness_blockers(validation) == ()


def test_cadcheck_parse_bbox():
    cadcheck = load_script("cadcheck.py")
    assert cadcheck.parse_bbox("40, 20,30") == (40.0, 20.0, 30.0)
    with pytest.raises(ValueError):
        cadcheck.parse_bbox("40,20")
    with pytest.raises(ValueError):
        cadcheck.parse_bbox("40,20,-1")


def test_cadcheck_passes_valid_facts_orientation_insensitively():
    cadcheck = load_script("cadcheck.py")
    facts = {
        "is_valid": True,
        "volume_mm3": 3890.2,
        "bbox_size_mm": [20.0, 40.0, 30.0],
    }
    failures = cadcheck.check_facts(
        facts, expect_bbox=(40.0, 20.0, 30.0), min_volume=3000.0
    )
    assert failures == []


def test_cadcheck_reports_each_failed_gate():
    cadcheck = load_script("cadcheck.py")
    facts = {"is_valid": False, "volume_mm3": 0.0, "bbox_size_mm": [1.0, 1.0, 1.0]}
    failures = cadcheck.check_facts(
        facts, expect_bbox=(40.0, 20.0, 30.0), min_volume=3000.0
    )
    assert any("valid" in failure for failure in failures)
    assert any("positive" in failure for failure in failures)
    assert any("minimum" in failure for failure in failures)
    assert any("bbox" in failure for failure in failures)


def test_cadcheck_bbox_tolerance_boundary():
    cadcheck = load_script("cadcheck.py")
    facts = {"is_valid": True, "volume_mm3": 1.0, "bbox_size_mm": [40.05, 20.0, 30.0]}
    assert cadcheck.check_facts(facts, expect_bbox=(40.0, 20.0, 30.0)) == []
    facts["bbox_size_mm"] = [40.5, 20.0, 30.0]
    assert cadcheck.check_facts(facts, expect_bbox=(40.0, 20.0, 30.0)) != []


def test_cadsnap_view_parsing_and_grid():
    cadsnap = load_script("cadsnap.py")
    assert cadsnap.parse_views("iso, top") == ["iso", "top"]
    with pytest.raises(ValueError):
        cadsnap.parse_views("iso,sideways")
    assert cadsnap.grid_shape(1) == (1, 1)
    assert cadsnap.grid_shape(4) == (2, 2)
    assert cadsnap.grid_shape(5) == (2, 3)


def test_zoo_submit_request_shape():
    zoo = load_script("zoo_text_to_cad.py")
    url, body = zoo.build_submit_request("a 40mm gear", "step")
    assert url == "https://api.zoo.dev/ai/text-to-cad/step"
    assert b'"prompt"' in body and b"a 40mm gear" in body
    assert zoo.poll_url("abc-123") == "https://api.zoo.dev/user/text-to-cad/abc-123"


def test_zoo_rejects_bad_inputs():
    zoo = load_script("zoo_text_to_cad.py")
    with pytest.raises(ValueError):
        zoo.build_submit_request("a gear", "dwg")
    with pytest.raises(ValueError):
        zoo.build_submit_request("   ", "step")


def test_zoo_requires_token(monkeypatch):
    zoo = load_script("zoo_text_to_cad.py")
    monkeypatch.delenv("ZOO_API_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="ZOO_API_TOKEN"):
        zoo.require_token()


def test_scripts_never_import_heavy_deps_at_module_level():
    before = set(sys.modules)
    for name in ("cadcheck.py", "cadsnap.py", "zoo_text_to_cad.py"):
        load_script(name)
    imported = set(sys.modules) - before
    for heavy in ("build123d", "stl", "matplotlib"):
        assert heavy not in imported, (
            f"{heavy} must only be imported inside functions so the skill "
            "scripts stay importable without the skill venv"
        )
