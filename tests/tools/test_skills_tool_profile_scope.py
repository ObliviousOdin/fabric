"""Regression tests for profile-scoped skills_tool path resolution."""

import importlib
import json
from pathlib import Path


def _write_skill(root: Path, category: str, name: str, description: str) -> Path:
    skill_dir = root / "skills" / category / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"Loaded from {description}.\n",
        encoding="utf-8",
    )
    return skill_dir


def _reload_skills_tool(import_home: Path, monkeypatch):
    monkeypatch.setenv("FABRIC_HOME", str(import_home))
    import tools.skills_tool as skills_tool

    return importlib.reload(skills_tool)


def test_skill_view_uses_live_profile_home_after_module_import(tmp_path, monkeypatch):
    """skill_view should not stay pinned to FABRIC_HOME from import time."""
    default_home = tmp_path / "default-home"
    profile_home = tmp_path / "profiles" / "orchestrator"
    _write_skill(default_home, "autonomous-ai-agents", "default-only", "default home")
    profile_skill_dir = _write_skill(
        profile_home,
        "software-development",
        "kanban-orchestrator-operations",
        "orchestrator profile",
    )

    skills_tool = _reload_skills_tool(default_home, monkeypatch)
    assert skills_tool._skills_dir() == default_home / "skills"

    monkeypatch.setenv("FABRIC_HOME", str(profile_home))

    result = json.loads(
        skills_tool.skill_view("kanban-orchestrator-operations", preprocess=False)
    )

    assert result["success"] is True
    assert result["name"] == "kanban-orchestrator-operations"
    assert Path(result["skill_dir"]) == profile_skill_dir
    assert "orchestrator profile" in result["content"]


def test_skills_list_uses_live_profile_home_after_module_import(tmp_path, monkeypatch):
    """skills_list should list the active profile skills, not the import-time root."""
    default_home = tmp_path / "default-home"
    profile_home = tmp_path / "profiles" / "orchestrator"
    _write_skill(default_home, "autonomous-ai-agents", "default-only", "default home")
    _write_skill(
        profile_home,
        "software-development",
        "kanban-orchestrator-operations",
        "orchestrator profile",
    )

    skills_tool = _reload_skills_tool(default_home, monkeypatch)
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))

    result = json.loads(skills_tool.skills_list())
    names = {skill["name"] for skill in result["skills"]}

    assert result["success"] is True
    assert "kanban-orchestrator-operations" in names
    assert "default-only" not in names


def test_skills_tool_has_no_import_time_path_aliases(tmp_path, monkeypatch):
    """The profile-aware getter is the only skills-directory contract."""
    default_home = tmp_path / "default-home"
    profile_home = tmp_path / "profiles" / "orchestrator"

    skills_tool = _reload_skills_tool(default_home, monkeypatch)
    monkeypatch.setenv("FABRIC_HOME", str(profile_home))

    assert not hasattr(skills_tool, "SKILLS_DIR")
    assert not hasattr(skills_tool, "FABRIC_HOME")
    assert skills_tool._skills_dir() == profile_home / "skills"
