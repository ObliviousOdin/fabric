from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_brand_assets.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("fabric_brand_asset_builder", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FabricBrandAssetBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.builder = _load_builder()

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.output = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_bundle_is_deterministic_and_uses_canonical_primary(self) -> None:
        first = self.output / "first"
        second = self.output / "second"

        first_manifest = self.builder.generate_assets(first)
        second_manifest = self.builder.generate_assets(second)

        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(first_manifest["canonicalPrimary"], "#4628CC")
        self.assertEqual(
            sorted(path.name for path in first.iterdir()),
            sorted(path.name for path in second.iterdir()),
        )
        for first_path in first.iterdir():
            self.assertEqual(
                first_path.read_bytes(),
                (second / first_path.name).read_bytes(),
                first_path.name,
            )

    def test_png_ico_and_icns_outputs_have_expected_geometry(self) -> None:
        self.builder.generate_assets(self.output)

        with Image.open(self.output / "fabric-mark-192.png") as mark:
            self.assertEqual(mark.size, (192, 192))
            self.assertEqual(mark.mode, "RGBA")
            self.assertEqual(mark.getpixel((0, 0))[3], 0)
            center_pixel = mark.getpixel((96, 96))
            self.assertIsInstance(center_pixel, tuple)
            assert isinstance(center_pixel, tuple)
            self.assertGreater(center_pixel[3], 250)
            center_color = center_pixel[:3]
            self.assertNotEqual(center_color, (70, 40, 204))

        with Image.open(self.output / "fabric-app-icon-192.png") as app_icon:
            self.assertEqual(app_icon.size, (192, 192))
            corner_pixel = app_icon.getpixel((0, 0))
            app_center_pixel = app_icon.getpixel((96, 96))
            self.assertIsInstance(corner_pixel, tuple)
            self.assertIsInstance(app_center_pixel, tuple)
            assert isinstance(corner_pixel, tuple)
            assert isinstance(app_center_pixel, tuple)
            self.assertEqual(corner_pixel[:3], (239, 238, 233))
            self.assertEqual(app_center_pixel[:3], center_color)

        with Image.open(self.output / "fabric-maskable-512.png") as maskable:
            self.assertEqual(maskable.getpixel((0, 0))[:3], (70, 40, 204))
            self.assertEqual(maskable.getpixel((256, 256))[:3], (255, 255, 255))
            white_pixels = (
                (x, y)
                for y in range(maskable.height)
                for x in range(maskable.width)
                if all(channel >= 250 for channel in maskable.getpixel((x, y))[:3])
            )
            farthest = max(
                ((x - 256) ** 2 + (y - 256) ** 2) ** 0.5
                for x, y in white_pixels
            )
            self.assertLessEqual(farthest, 512 * 0.4)

        with Image.open(self.output / "fabric-favicon.ico") as favicon:
            self.assertEqual(favicon.format, "ICO")
            self.assertIn((16, 16), favicon.info["sizes"])
            self.assertIn((256, 256), favicon.info["sizes"])

        with Image.open(self.output / "fabric-app-icon.icns") as app_icns:
            self.assertEqual(app_icns.format, "ICNS")
            self.assertEqual(app_icns.size, (1024, 1024))

    def test_raster_gradient_uses_canonical_svg_bounds(self) -> None:
        square = [[(0, 0), (128, 0), (128, 128), (0, 128), (0, 0)]]
        master = self.builder._render_master(  # noqa: SLF001
            (0, 0, 128, 128),
            square,
            foreground=None,
            background=None,
        )
        pixel_x = round(32 / 128 * (self.builder.MASTER_SIZE - 1))
        user_x = pixel_x / (self.builder.MASTER_SIZE - 1) * 128
        start, end = self.builder.MARK_GRADIENT_X_RANGE
        position = (user_x - start) / (end - start)
        stops = [
            (offset, self.builder.ImageColor.getrgb(color))
            for offset, color in self.builder.MARK_GRADIENT_STOPS
        ]
        for index, (right_offset, right_color) in enumerate(stops[1:], start=1):
            if position <= right_offset:
                left_offset, left_color = stops[index - 1]
                amount = (position - left_offset) / (right_offset - left_offset)
                expected = tuple(
                    round(left + (right - left) * amount)
                    for left, right in zip(left_color, right_color, strict=True)
                )
                break
        else:
            expected = stops[-1][1]

        self.assertEqual(master.getpixel((pixel_x, 64))[:3], expected)

    def test_manifest_hashes_every_generated_asset(self) -> None:
        self.builder.generate_assets(self.output)
        manifest = json.loads(
            (self.output / "brand-assets.json").read_text(encoding="utf-8")
        )

        self.assertIn("fabric-wordmark.svg", manifest["assets"])
        self.assertIn("fabric-wordmark-on-dark.svg", manifest["assets"])
        self.assertIn("fabric-app-icon-180.png", manifest["assets"])
        self.assertIn("fabric-app-icon-192.png", manifest["assets"])
        self.assertIn("fabric-favicon.ico", manifest["assets"])
        self.assertIn("fabric-app-icon.icns", manifest["assets"])
        self.assertNotIn("reference-mark.jpg", manifest["assets"])
        reference = manifest["sources"]["reference-mark.jpg"]
        self.assertEqual(reference["width"], 1024)
        self.assertEqual(reference["height"], 1024)
        self.assertEqual(
            reference["sha256"],
            "934aebaece6894fed26fa6bb61d9672672d7091142f8096684d36ecf34fee8c4",
        )
        for name, record in manifest["assets"].items():
            self.assertEqual(
                record["sha256"],
                self.builder._sha256(self.output / name),  # noqa: SLF001
                name,
            )

    def test_check_reports_modified_asset_without_rewriting_it(self) -> None:
        self.builder.generate_assets(self.output)
        target = self.output / "fabric-mark-32.png"
        target.write_bytes(b"not a png")

        issues = self.builder.check_assets(self.output)

        self.assertIn("fabric-mark-32.png: stale", issues)
        self.assertEqual(target.read_bytes(), b"not a png")

    def test_source_contract_is_vector_and_keeps_bracket_out_of_mark(self) -> None:
        source = self.builder.SOURCE_DIR
        mark = (source / "mark.svg").read_text(encoding="utf-8")
        mark_root = ET.fromstring(mark)
        wordmark = (source / "wordmark.svg").read_text(encoding="utf-8")

        self.assertIn('id="fabric-mark-gradient"', mark)
        gradient = next(
            element
            for element in mark_root.iter()
            if element.attrib.get("id") == "fabric-mark-gradient"
        )
        self.assertEqual(
            tuple(float(gradient.attrib[name]) for name in ("x1", "x2")),
            self.builder.MARK_GRADIENT_X_RANGE,
        )
        self.assertEqual(mark.count('data-fabric-mark="true"'), 2)
        self.assertNotIn("data-fabric-bracket", mark)
        self.assertNotIn("<text", wordmark)
        self.assertIn('data-fabric-symbol="true"', wordmark)
        self.assertIn('data-fabric-bracket="true"', wordmark)
        self.assertTrue((source / "reference-mark.jpg").is_file())
        self.assertFalse(list((source.parents[1] / "fonts").glob("*.woff*")))


if __name__ == "__main__":
    unittest.main()
