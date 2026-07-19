"""Distribution-path contract for bundled capability packs."""

from pathlib import Path

import fabric_constants


def test_bundled_capability_packs_prefers_packaged_data(tmp_path, monkeypatch):
    packaged = tmp_path / "wheel-data" / "capability-packs"
    default = tmp_path / "checkout" / "capability-packs"
    requested: list[str] = []

    def resolve_packaged_data(name: str) -> Path | None:
        requested.append(name)
        return packaged

    monkeypatch.setattr(
        fabric_constants, "_get_packaged_data_dir", resolve_packaged_data
    )

    assert fabric_constants.get_bundled_capability_packs_dir(default) == packaged
    assert requested == ["capability-packs"]


def test_bundled_capability_packs_uses_only_explicit_default(tmp_path, monkeypatch):
    default = tmp_path / "checkout" / "capability-packs"
    ambient = tmp_path / "ambient"
    monkeypatch.setattr(fabric_constants, "_get_packaged_data_dir", lambda _name: None)
    monkeypatch.setattr(
        fabric_constants,
        "get_fabric_home",
        lambda: (_ for _ in ()).throw(AssertionError("profile fallback was read")),
    )
    monkeypatch.setenv("FABRIC_HOME", str(ambient / "fabric-home"))

    assert fabric_constants.get_bundled_capability_packs_dir(default) == default
