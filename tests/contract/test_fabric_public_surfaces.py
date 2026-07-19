"""Contract: resolved public product strings stay Fabric-native."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fabric-brand-audit.py"
FORMER_PRODUCT = "Her" + "mes"
FORMER_LOWER = FORMER_PRODUCT.lower()


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("fabric_brand_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_fabric_brand_audit_script_passes():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "public"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_native_guide_audit_rejects_upstream_commands_and_installers(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        f"# Fabric\n\n```bash\n{FORMER_LOWER} model\n```\n"
        f"https://github.com/NousResearch/{FORMER_LOWER}-agent/install.sh\n",
        encoding="utf-8",
    )

    issues = audit.audit_native_guides(tmp_path, ("guide.md",))

    assert any("legacy CLI command" in issue for issue in issues)
    assert any("legacy repository/docs route" in issue for issue in issues)


def test_native_guide_audit_rejects_retired_model_attribution(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        f"# Fabric\n\n{FORMER_PRODUCT} 3 by Nous Research is an available model.\n\n"
        "```bash\nfabric status\n```\n",
        encoding="utf-8",
    )

    assert audit.audit_native_guides(tmp_path, ("guide.md",))


def test_native_guide_audit_rejects_historical_upstream_citations(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        "# Fabric\n\n```bash\nfabric status\n```\n"
        "Historical context: "
        f"https://github.com/NousResearch/{FORMER_LOWER}-agent/issues/26847\n",
        encoding="utf-8",
    )

    assert audit.audit_native_guides(tmp_path, ("guide.md",))


def test_public_discovery_audit_rejects_upstream_product_identity(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    homepage = tmp_path / "homepage.md"
    homepage.write_text("# Fabric\n\nRecommended by Nous Portal.\n", encoding="utf-8")

    issues = audit.audit_public_site_sources(tmp_path, ("homepage.md",))

    assert any("public discovery surface" in issue for issue in issues)


def test_public_discovery_audit_does_not_scan_provider_detail_pages(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    homepage = tmp_path / "homepage.md"
    provider = tmp_path / "provider.md"
    homepage.write_text("# Fabric\n\nChoose a model route.\n", encoding="utf-8")
    provider.write_text(
        "# Optional provider\n\nNous is a third-party provider identifier.\n",
        encoding="utf-8",
    )

    assert audit.audit_public_site_sources(tmp_path, ("homepage.md",)) == []


def test_built_public_site_audit_checks_rendered_entry_points(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    for relative in audit.BUILT_PUBLIC_DISCOVERY_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Fabric", encoding="utf-8")
    (tmp_path / "index.html").write_text(
        f"<html><body>{FORMER_PRODUCT} Agent</body></html>",
        encoding="utf-8",
    )

    issues = audit.audit_built_public_site(tmp_path)

    assert any(issue.startswith("index.html:") for issue in issues)


def test_native_guide_audit_rejects_non_provenance_upstream_support_route(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        "# Fabric\n\n```bash\nfabric status\n```\n"
        f"https://github.com/NousResearch/{FORMER_LOWER}-agent/issues/new\n",
        encoding="utf-8",
    )

    issues = audit.audit_native_guides(tmp_path, ("guide.md",))

    assert any("legacy repository/docs route" in issue for issue in issues)
