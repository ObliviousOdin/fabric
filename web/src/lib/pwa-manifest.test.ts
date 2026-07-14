/// <reference types="node" />

import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

interface ManifestIcon {
  purpose?: string;
  sizes: string;
  src: string;
  type: string;
}

interface WebAppManifest {
  background_color: string;
  display: string;
  icons: ManifestIcon[];
  name: string;
  scope: string;
  short_name: string;
  start_url: string;
  theme_color: string;
}

const publicDir = fileURLToPath(new URL("../../public/", import.meta.url));
const manifestPath = fileURLToPath(
  new URL("../../public/manifest.webmanifest", import.meta.url),
);
const indexPath = fileURLToPath(new URL("../../index.html", import.meta.url));

function pngDimensions(path: string): { height: number; width: number } {
  const bytes = readFileSync(path);
  expect(bytes.subarray(1, 4).toString("ascii")).toBe("PNG");
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

describe("mobile web app manifest", () => {
  it("launches the existing chat experience as a standalone scoped app", () => {
    const manifest = JSON.parse(
      readFileSync(manifestPath, "utf8"),
    ) as WebAppManifest;

    expect(manifest.name).toBe("Fabric");
    expect(manifest.short_name).toBe("Fabric");
    expect(manifest.display).toBe("standalone");
    expect(manifest.scope).toBe("./");
    expect(manifest.start_url).toBe("./chat");
    expect(manifest.background_color).toBe("#f8fafe");
    expect(manifest.theme_color).toBe("#f8fafe");
  });

  it("keeps every declared PNG icon present and dimensionally honest", () => {
    const manifest = JSON.parse(
      readFileSync(manifestPath, "utf8"),
    ) as WebAppManifest;

    expect(manifest.icons.length).toBeGreaterThanOrEqual(2);
    const declaredSizes = new Set(
      manifest.icons.flatMap((icon) => icon.sizes.trim().split(/\s+/)),
    );
    expect(declaredSizes).toContain("192x192");
    expect(declaredSizes).toContain("512x512");

    for (const icon of manifest.icons) {
      expect(icon.type).toBe("image/png");
      expect(icon.purpose?.split(" ")).toContain("any");

      const iconPath = `${publicDir}${icon.src}`;
      expect(existsSync(iconPath), icon.src).toBe(true);

      const [expectedWidth, expectedHeight] = icon.sizes.split("x").map(Number);
      expect(pngDimensions(iconPath)).toEqual({
        width: expectedWidth,
        height: expectedHeight,
      });
    }
  });

  it("links the manifest and iOS home-screen metadata from the app shell", () => {
    const html = readFileSync(indexPath, "utf8");

    expect(html).toContain('rel="manifest"');
    expect(html).toContain('crossorigin="use-credentials"');
    expect(html).toContain('rel="apple-touch-icon"');
    expect(html).toContain('name="apple-mobile-web-app-capable"');
    expect(html).toContain(
      'content="width=device-width, initial-scale=1.0, viewport-fit=cover"',
    );
  });
});
