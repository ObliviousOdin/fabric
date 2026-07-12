"""Contract: resolved public product strings stay Fabric-native."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fabric-brand-audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("fabric_brand_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_SOURCE_SCAN_EXCLUDED = {
    ".venv",
    "docs",
    "node_modules",
    "optional-skills",
    "skills",
    "tests",
    "ui-tui",
    "venv",
    "website",
}

# These strings describe or implement the one-time legacy-home migration and
# compatibility aliases. They are not normal Fabric runtime guidance.
_LEGACY_HOME_LITERAL_ALLOWLIST = {
    "fabric_cli/fabric_soul_migrate.py": None,
    "gateway/platforms/webhook_filters.py": ("~/.hermes",),
    # Remote execution backends still mount their internal sandbox cache here;
    # this is an agent-visible transport path, not customer setup guidance.
    "tools/image_generation_tool.py": ("~/.hermes",),
    "fabric_cli/main.py": (
        "Safely migrate ~/.hermes customer data to ~/.fabric",
        "Copy the legacy home to a staged ~/.fabric tree",
        "Legacy home (default: ~/.hermes)",
        "Leave ~/.hermes in place instead of renaming it",
    ),
}


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    docstrings = set()
    for owner in ast.walk(tree):
        if not isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not owner.body:
            continue
        first = owner.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def _allowlisted_legacy_literal(relative_path: str, value: str) -> bool:
    allowed = _LEGACY_HOME_LITERAL_ALLOWLIST.get(relative_path, ())
    if allowed is None:
        return relative_path in _LEGACY_HOME_LITERAL_ALLOWLIST
    return any(fragment in value for fragment in allowed)


def test_public_runtime_guidance_uses_fabric_home():
    leaks = []
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if any(part in _SOURCE_SCAN_EXCLUDED for part in relative.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        docstring_ids = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Constant)
                or not isinstance(node.value, str)
                or "~/.hermes" not in node.value
                or id(node) in docstring_ids
            ):
                continue
            relative_text = relative.as_posix()
            if _allowlisted_legacy_literal(relative_text, node.value):
                continue
            leaks.append(f"{relative_text}:{getattr(node, 'lineno', '?')}")
    assert not leaks, f"legacy home path remains in emitted runtime strings: {leaks}"


def test_fabric_brand_audit_script_passes():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "public"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={**dict(**__import__("os").environ), "FABRIC_BRAND": "1"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_native_guide_audit_rejects_upstream_commands_and_installers(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        "# Fabric\n\n```bash\nhermes model\n```\n"
        "https://raw.githubusercontent.com/NousResearch/fabric-agent/main/scripts/install.sh\n",
        encoding="utf-8",
    )

    issues = audit.audit_native_guides(tmp_path, ("guide.md",))

    assert any("legacy CLI command" in issue for issue in issues)
    assert any("legacy repository/docs route" in issue for issue in issues)


def test_native_guide_audit_accepts_model_attribution_but_requires_fabric_command(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        "# Fabric\n\nHermes 3 by Nous Research is an available model.\n\n"
        "```bash\nfabric status\n```\n",
        encoding="utf-8",
    )

    assert audit.audit_native_guides(tmp_path, ("guide.md",)) == []


def test_native_guide_audit_allows_exact_historical_upstream_citations(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        "# Fabric\n\n```bash\nfabric status\n```\n"
        "Historical context: "
        "https://github.com/NousResearch/hermes-agent/issues/26847\n",
        encoding="utf-8",
    )

    assert audit.audit_native_guides(tmp_path, ("guide.md",)) == []


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
        "<html><body>Hermes Agent</body></html>",
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
        "https://github.com/NousResearch/hermes-agent/issues/new\n",
        encoding="utf-8",
    )

    issues = audit.audit_native_guides(tmp_path, ("guide.md",))

    assert any("legacy repository/docs route" in issue for issue in issues)
