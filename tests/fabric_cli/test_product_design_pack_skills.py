"""Source contracts for Fabric's original Product Design capability skills."""

from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = REPOSITORY_ROOT / "capability-packs" / "fabric.product-design" / "1.0.0"
SKILLS = {
    "product-design": PACK_ROOT / "router",
    "design-brief": PACK_ROOT / "members" / "design-brief",
    "design-explore": PACK_ROOT / "members" / "design-explore",
    "design-build": PACK_ROOT / "members" / "design-build",
    "design-review": PACK_ROOT / "members" / "design-review",
}


def _skill_parts(skill_root: Path) -> tuple[dict[str, str], str]:
    raw = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    _start, frontmatter_raw, body = raw.split("---\n", 2)
    frontmatter = yaml.safe_load(frontmatter_raw)
    assert isinstance(frontmatter, dict)
    return frontmatter, body


def test_product_design_skills_have_minimal_supported_frontmatter() -> None:
    for expected_name, skill_root in SKILLS.items():
        frontmatter, body = _skill_parts(skill_root)
        assert set(frontmatter) == {"name", "description"}
        assert frontmatter["name"] == expected_name
        assert len(frontmatter["description"].strip()) >= 80
        assert body.strip().startswith("# Fabric")
        assert "TODO" not in body


def test_product_design_skill_ui_metadata_is_fabric_branded() -> None:
    for skill_root in SKILLS.values():
        data = yaml.safe_load(
            (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        interface = data["interface"]
        assert interface["display_name"].startswith("Fabric ")
        assert 20 <= len(interface["short_description"]) <= 80


def test_product_design_router_selects_one_member_without_doing_phase_work() -> None:
    _frontmatter, router = _skill_parts(SKILLS["product-design"])
    assert "Load exactly one member with `skill_view`" in router
    assert "Do not preload members" in router
    assert "Do not write the brief" in router
    for member in ("design-brief", "design-explore", "design-build", "design-review"):
        assert f"`{member}`" in router


def test_product_design_members_preserve_phase_stop_conditions() -> None:
    _brief_frontmatter, brief = _skill_parts(SKILLS["design-brief"])
    brief_flat = " ".join(brief.split())
    assert "Do not propose visual directions" in brief_flat
    assert "`DesignBrief`" in brief
    assert "acceptance_checks" in brief

    _explore_frontmatter, explore = _skill_parts(SKILLS["design-explore"])
    explore_flat = " ".join(explore.split())
    assert "at least three directions" in explore
    assert "selection_required" in explore
    assert "do not treat the recommendation as the user's selection" in explore_flat

    _build_frontmatter, build = _skill_parts(SKILLS["design-build"])
    build_flat = " ".join(build.split())
    assert "Require both an approved `DesignBrief`" in build_flat
    assert "Do not clone proprietary branded UI" in build
    assert "`ImplementationReceipt`" in build

    _review_frontmatter, review = _skill_parts(SKILLS["design-review"])
    review_flat = " ".join(review.split())
    assert "report-only" in review
    assert "only when the user also asked to implement or fix" in review_flat
    assert "Do not use `verified` for a source-only review" in review
