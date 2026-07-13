from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fabric-brand-audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("fabric_brand_audit_unit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FabricBrandAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = _load_audit_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _write_clean_build(self) -> None:
        for relative in self.audit.BUILT_PUBLIC_DISCOVERY_PATHS:
            self._write(relative, "Fabric")
        for relative in self.audit.BUILT_POSITIONING_ARTIFACT_PATHS:
            self._write(relative, '{"product":"Fabric"}')

    def test_discovery_audit_rejects_joined_and_structured_brand_variants(self) -> None:
        variants = (
            "NousPortal",
            "HermesAgent",
            "Ra" + "botInc",
            "RA" + "BOT_HOME",
        )
        for index, variant in enumerate(variants):
            relative = f"page-{index}.md"
            self._write(relative, f"# Fabric\n\n{variant}\n")
            with self.subTest(variant=variant):
                self.assertTrue(
                    self.audit.audit_public_site_sources(self.root, (relative,))
                )

    def test_exact_legacy_redirect_paths_are_allowed_but_labels_are_not(self) -> None:
        relative = "website/docusaurus.config.ts"
        redirects = "\n".join(
            self.audit.PUBLIC_DISCOVERY_EXACT_ALLOWLIST[relative]
        )
        path = self._write(relative, redirects)

        self.assertEqual(
            self.audit.audit_public_site_sources(self.root, (relative,)),
            [],
        )

        path.write_text(redirects + "\nlabel: 'Nous Portal'\n", encoding="utf-8")
        self.assertTrue(self.audit.audit_public_site_sources(self.root, (relative,)))

    def test_provider_attribution_is_allowed_outside_discovery_surfaces(self) -> None:
        self._write(
            "website/docs/providers/detail.md",
            "Nous is an optional third-party provider identifier.\n",
        )

        self.assertEqual(self.audit.audit_public_positioning_sources(self.root), [])

    def test_vendor_first_recommendation_fails_any_public_source(self) -> None:
        self._write(
            "website/docs/guide.md",
            "Nous Portal is the recommended way to run Fabric.\n",
        )

        self.assertTrue(self.audit.audit_public_positioning_sources(self.root))

    def test_legacy_upstream_media_id_fails_even_with_fabric_iframe_title(self) -> None:
        self._write(
            "website/docs/guide.md",
            '<iframe src="https://www.youtube.com/embed/WNYe5mD4fY8" '
            'title="Fabric tutorial" />\n',
        )

        issues = self.audit.audit_public_positioning_sources(self.root)

        self.assertTrue(
            any("legacy upstream media in public content" in issue for issue in issues)
        )

    def test_managed_vendor_bundle_promotion_fails(self) -> None:
        self._write(
            "website/docs/guide.md",
            "Paid Nous Portal subscribers can connect managed models with no "
            "separate API keys.\n",
        )

        issues = self.audit.audit_public_positioning_sources(self.root)

        self.assertTrue(any("upstream bundle promotion" in issue for issue in issues))

    def test_markdown_linked_vendor_bundle_promotion_fails(self) -> None:
        self._write(
            "website/docs/guide.md",
            "# Guide\n\nPaid [Nous Portal](https://example.com/portal) subscribers "
            "can use managed models with no separate API keys.\n",
        )

        issues = self.audit.audit_public_positioning_sources(self.root)

        self.assertTrue(
            any(
                issue.startswith("website/docs/guide.md:3:")
                and "upstream bundle promotion" in issue
                for issue in issues
            )
        )

    def test_html_linked_vendor_bundle_promotion_fails(self) -> None:
        text = (
            "<main>\n<p>Paid <a href=\"https://example.com/portal\">Nous Portal</a> "
            "subscribers can use managed models with no separate API keys.</p>\n"
            "</main>\n"
        )

        issues = self.audit._positioning_issues("index.html", text)  # noqa: SLF001

        self.assertTrue(
            any(
                issue.startswith("index.html:2:")
                and "upstream bundle promotion" in issue
                for issue in issues
            )
        )

    def test_subscription_without_api_keys_promotion_fails(self) -> None:
        self._write(
            "apps/desktop/src/store/onboarding.ts",
            "export const message = 'GPT-5 and Claude now run through your "
            "Nous subscription — no separate API keys needed.';\n",
        )

        issues = self.audit.audit_public_positioning_sources(self.root)

        self.assertTrue(any("upstream bundle promotion" in issue for issue in issues))

    def test_neutral_provider_comparison_is_not_a_vendor_recommendation(self) -> None:
        self._write(
            "website/docs/providers/detail.md",
            "Nous is optional. OpenRouter is the recommended provider.\n",
        )

        self.assertEqual(self.audit.audit_public_positioning_sources(self.root), [])

    def test_recommendation_match_does_not_cross_paragraphs(self) -> None:
        self._write(
            "website/docs/providers/detail.md",
            "Nous is an optional provider\n\n"
            "OpenRouter is the recommended provider.\n",
        )

        self.assertEqual(self.audit.audit_public_positioning_sources(self.root), [])

    def test_built_audit_covers_nav_and_footer_destinations(self) -> None:
        self._write_clean_build()
        self._write("skills/index.html", "<main>HermesAgent</main>")

        issues = self.audit.audit_built_public_site(self.root)

        self.assertTrue(any(issue.startswith("skills/index.html:") for issue in issues))

    def test_built_audit_covers_search_and_full_document_exports(self) -> None:
        self._write_clean_build()
        self._write(
            "search-index.json",
            '{"text":"Nous Portal is the fastest path for Fabric"}',
        )

        issues = self.audit.audit_built_positioning_artifacts(self.root)

        self.assertTrue(any(issue.startswith("search-index.json:") for issue in issues))

    def test_clean_built_site_passes_both_layers(self) -> None:
        self._write_clean_build()

        self.assertEqual(self.audit.audit_built_public_site(self.root), [])
        self.assertEqual(self.audit.audit_built_positioning_artifacts(self.root), [])


if __name__ == "__main__":
    unittest.main()
