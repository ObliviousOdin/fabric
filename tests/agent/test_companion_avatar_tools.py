"""Regression coverage for the companion's personal avatar studio."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "apps" / "companion" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import pixel_avatars  # type: ignore[import-not-found]  # noqa: E402


def test_custom_avatar_assets_resolve_from_the_module_directory(tmp_path, monkeypatch):
    studio = tmp_path / "studio"
    refs = studio / "refs"
    refs.mkdir(parents=True)

    master = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for x in range(4, 12):
        for y in range(3, 14):
            master.putpixel((x, y), (253, 192, 93, 255))
    master.save(refs / "idle.png")

    (studio / "avatar_relative.py").write_text(
        """from avatar_from_image import bitmap_avatar

_pet = bitmap_avatar(
    name="Relative",
    slug="relative",
    description="Loads assets beside the custom module",
    image="refs/idle.png",
    poses={"idle": "refs/idle.png", "waving": ["refs/idle.png"]},
)
NAME, SLUG, DESCRIPTION, draw = _pet.NAME, _pet.SLUG, _pet.DESCRIPTION, _pet.draw
""",
        encoding="utf-8",
    )

    launch_dir = tmp_path / "elsewhere"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)

    modules = pixel_avatars._load_custom_modules(studio)

    assert Path.cwd() == launch_dir
    assert [module.SLUG for module in modules] == ["relative"]
    assert modules[0]._pet.multi_pose is True
    assert modules[0]._pet.poses == ["idle", "waving"]
    assert modules[0].draw("idle", 0, 4).getbbox() is not None
