"""Source contracts for Fabric's original Compound Engineering capability skills."""

from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = (
    REPOSITORY_ROOT / "capability-packs" / "fabric.compound-engineering" / "1.0.0"
)
SKILLS = {
    "compound-engineering": PACK_ROOT / "router",
    "compound-spike": PACK_ROOT / "members" / "compound-spike",
    "compound-plan": PACK_ROOT / "members" / "compound-plan",
    "compound-debug": PACK_ROOT / "members" / "compound-debug",
    "compound-test": PACK_ROOT / "members" / "compound-test",
    "compound-review": PACK_ROOT / "members" / "compound-review",
    "compound-capture": PACK_ROOT / "members" / "compound-capture",
}


def _skill_parts(skill_root: Path) -> tuple[dict[str, str], str]:
    raw = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    _start, frontmatter_raw, body = raw.split("---\n", 2)
    frontmatter = yaml.safe_load(frontmatter_raw)
    assert isinstance(frontmatter, dict)
    return frontmatter, body


def test_compound_engineering_skills_have_minimal_supported_frontmatter() -> None:
    for expected_name, skill_root in SKILLS.items():
        frontmatter, body = _skill_parts(skill_root)
        assert set(frontmatter) == {"name", "description"}
        assert frontmatter["name"] == expected_name
        assert len(frontmatter["description"].strip()) >= 80
        assert body.strip().startswith("# Fabric")
        assert "TODO" not in body


def test_compound_engineering_skill_ui_metadata_is_fabric_branded() -> None:
    for skill_root in SKILLS.values():
        data = yaml.safe_load(
            (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        interface = data["interface"]
        assert interface["display_name"].startswith("Fabric ")
        assert 20 <= len(interface["short_description"]) <= 80


def test_compound_router_selects_exactly_one_member_without_phase_work() -> None:
    _frontmatter, router = _skill_parts(SKILLS["compound-engineering"])
    router_flat = " ".join(router.split())
    assert "Load exactly one member with `skill_view`" in router_flat
    assert "Never preload multiple members" in router_flat
    assert "Do not investigate, plan, implement, review, or capture" in router_flat
    for member in (
        "compound-spike",
        "compound-plan",
        "compound-debug",
        "compound-test",
        "compound-review",
        "compound-capture",
    ):
        assert f"`{member}`" in router


def test_debug_requires_causal_proof_before_a_fix_handoff() -> None:
    _frontmatter, debug = _skill_parts(SKILLS["compound-debug"])
    debug_flat = " ".join(debug.split())
    assert "Diagnose before repair" in debug
    assert (
        "A correlation, nearby code smell, or passing mock is not a root cause" in debug
    )
    assert (
        "only when the causal chain is proven and the user requested a fix"
        in debug_flat
    )
    assert "`DebugDiagnosis`" in debug


def test_implementation_requires_evidence_authority_and_red_green_proof() -> None:
    _frontmatter, implementation = _skill_parts(SKILLS["compound-test"])
    implementation_flat = " ".join(implementation.split())
    assert "approved `EngineeringPlan` or proven `DebugDiagnosis`" in implementation
    assert "explicit authority to change the scoped workspace" in implementation_flat
    assert "Run the guard before implementation" in implementation_flat
    assert "failing-before" in implementation
    assert "passing-after" in implementation
    assert "Do not mark the work independently verified yourself" in implementation


def test_review_is_report_only_and_cannot_mutate() -> None:
    frontmatter, review = _skill_parts(SKILLS["compound-review"])
    review_flat = " ".join(review.split())
    assert "Review independently and report only" in review
    assert "Do not edit files" in review
    assert "even if fixes appear obvious" in review_flat
    for mutation in ("fixes", "stages", "commits", "stashes", "resets", "deploys"):
        assert mutation in frontmatter["description"]


def test_capture_requires_approval_authority_and_future_reuse_proof() -> None:
    _frontmatter, capture = _skill_parts(SKILLS["compound-capture"])
    capture_flat = " ".join(capture.split())
    assert "Require an approved `ReviewReceipt`" in capture
    assert "authority for the destination" in capture_flat
    assert "a specific retrieval cue for a future task" in capture_flat
    assert "only a separate later task may produce `reuse_verified`" in capture_flat
    assert "`CaptureReceipt`" in capture
