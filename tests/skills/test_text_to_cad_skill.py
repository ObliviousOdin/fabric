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
    for name in (
        "cadcheck.py",
        "cadsnap.py",
        "zoo_text_to_cad.py",
        "stdparts.py",
        "assembly.py",
        "printcheck.py",
        "dxfcheck.py",
        "cadviewer.py",
    ):
        load_script(name)
    imported = set(sys.modules) - before
    for heavy in ("build123d", "stl", "matplotlib", "ezdxf"):
        assert heavy not in imported, (
            f"{heavy} must only be imported inside functions so the skill "
            "scripts stay importable without the skill venv"
        )


# --- stack additions -------------------------------------------------------


def test_stdparts_specs_and_geometry_helpers():
    stdparts = load_script("stdparts.py")
    for table in (stdparts.SCREW_SPECS, stdparts.NUT_SPECS, stdparts.WASHER_SPECS):
        assert "M4" in table and len(table["M4"]) == 3
    # Across-flats 7 -> circumradius 7/sqrt(3).
    assert stdparts.circumradius_from_across_flats(7.0) == pytest.approx(4.0415, abs=1e-3)


def test_stdparts_validates_inputs_without_deps():
    stdparts = load_script("stdparts.py")
    with pytest.raises(ValueError):
        stdparts.make_screw("M99", 10)          # unknown size (checked pre-import)
    with pytest.raises(ValueError):
        stdparts.make_screw("M4", -1)           # bad length (checked pre-import)


def test_assembly_placement_parsing():
    assembly = load_script("assembly.py")
    plain = assembly.parse_placement("base.step:1,2,3")
    assert plain.offset == (1.0, 2.0, 3.0) and plain.rz == 0.0 and plain.label == "base"
    rotated = assembly.parse_placement("lid.step:0,0,20:rz=90")
    assert rotated.rz == 90.0
    for bad in ("nocolon.step", "p.step:0,0", "p.step:0,0,0:foo=1"):
        with pytest.raises(ValueError):
            assembly.parse_placement(bad)


def test_assembly_bbox_overlap():
    assembly = load_script("assembly.py")
    a = {"min": (0, 0, 0), "max": (10, 10, 10)}
    b = {"min": (5, 5, 5), "max": (15, 15, 15)}
    touching = {"min": (10, 0, 0), "max": (20, 10, 10)}
    assert assembly.boxes_overlap(a, b) is True
    assert assembly.boxes_overlap(a, touching) is False   # shared face, not overlap
    assert assembly.boxes_overlap(a, b, clearance=6.0) is False


def test_printcheck_bed_fit_and_overhang():
    printcheck = load_script("printcheck.py")
    assert printcheck.parse_bed("220, 220,250") == (220.0, 220.0, 250.0)
    # Footprint rotates: 100x50 fits a 60x120 bed.
    assert printcheck.fits_bed((100.0, 50.0, 20.0), (60.0, 120.0, 250.0)) is True
    assert printcheck.fits_bed((100.0, 50.0, 300.0), (60.0, 120.0, 250.0)) is False
    # A flat bottom (normal down) is a steep overhang; a vertical wall is not.
    assert printcheck.overhang_fraction([-1.0], [1.0], 45.0) == pytest.approx(1.0)
    assert printcheck.overhang_fraction([0.0], [1.0], 45.0) == pytest.approx(0.0)


def test_dxfcheck_segment_closure():
    dxfcheck = load_script("dxfcheck.py")
    square = [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 10)),
        ((10, 10), (0, 10)),
        ((0, 10), (0, 0)),
    ]
    assert dxfcheck.analyze_segments(square) == (1, 0)
    assert dxfcheck.analyze_segments([((0, 0), (10, 0))]) == (0, 2)
    assert dxfcheck.analyze_segments([]) == (0, 0)

    open_edges, isolated = dxfcheck.polyline_segments([(20, 0), (30, 0), (30, 10)], False)
    assert dxfcheck.analyze_segments(square + open_edges) == (0, 2)
    assert isolated == 0
    assert dxfcheck.polyline_segments([(20, 0)], False) == ([], 1)


def test_cadviewer_page_embeds_model():
    cadviewer = load_script("cadviewer.py")
    page = cadviewer.render_page(b"GLBDATA", "Bracket & Co")
    assert "<model-viewer" in page
    assert "model/gltf-binary;base64," in page
    assert "Bracket &amp; Co" in page          # title HTML-escaped
    with pytest.raises(ValueError):
        cadviewer.render_page(b"", "empty")
