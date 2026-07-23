import assert from "node:assert/strict";
import test from "node:test";

import {
  fetchLatestDesktopRelease,
  resolveLatestDesktopRelease,
  validateDesktopManifest,
} from "./latest-desktop-release.mjs";

const manifest = {
  schema_version: 1,
  repository: "ObliviousOdin/fabric",
  tag: "v2026.7.22",
  source_sha: "a".repeat(40),
  desktop_app_version: "0.22.0",
  platforms: ["mac", "win"],
  files: [
    {
      name: "Fabric-0.22.0-mac-arm64.dmg",
      ext: "dmg",
      arch: "arm64",
      platform: "mac",
      size: 10,
      sha256: "b".repeat(64),
    },
  ],
};

test("resolves the newest release carrying desktop assets and reports a publishing gap", async () => {
  const payload = await resolveLatestDesktopRelease(
    [
      { tag_name: "v2026.7.23", draft: false, prerelease: false, assets: [] },
      {
        tag_name: "v2026.7.22",
        draft: false,
        prerelease: false,
        published_at: "2026-07-22T12:00:00Z",
        assets: [{ name: "desktop-release-manifest.json" }],
      },
    ],
    async () => manifest,
    "2026-07-23T00:00:00Z",
  );

  assert.equal(payload.status, "ready");
  assert.equal(payload.desktop_release.tag, "v2026.7.22");
  assert.equal(payload.publishing, true);
  assert.match(payload.desktop_release.files[0].url, /Fabric-0.22.0-mac-arm64\.dmg$/);
});

test("returns a valid unavailable payload when no release has desktop assets", async () => {
  const payload = await resolveLatestDesktopRelease(
    [{ tag_name: "v2026.7.23", draft: false, prerelease: false, assets: [] }],
    async () => {
      throw new Error("not called");
    },
  );
  assert.equal(payload.status, "unavailable");
  assert.equal(payload.desktop_release, null);
});

test("rejects noncanonical repositories and traversal", () => {
  assert.throws(
    () => validateDesktopManifest({ ...manifest, repository: "someone/fork" }),
    /Invalid desktop release manifest/,
  );
  assert.throws(
    () =>
      validateDesktopManifest({
        ...manifest,
        files: [{ ...manifest.files[0], name: "../Fabric.dmg" }],
      }),
    /Invalid desktop release file/,
  );
});

test("fetches later release pages when CLI-only releases fill the first page", async () => {
  const urls = [];
  const cliOnlyRelease = {
    tag_name: "v2026.7.24",
    draft: false,
    prerelease: false,
    assets: [],
  };
  const payload = await fetchLatestDesktopRelease({
    token: "test-token",
    fetchImpl: async (url) => {
      urls.push(url);
      const page = new URL(url).searchParams.get("page");
      const body =
        page === "1"
          ? Array.from({ length: 100 }, () => cliOnlyRelease)
          : page === "2"
            ? [
                {
                  tag_name: manifest.tag,
                  draft: false,
                  prerelease: false,
                  assets: [{ name: "desktop-release-manifest.json" }],
                },
              ]
            : manifest;
      return {
        ok: true,
        json: async () => body,
      };
    },
  });

  assert.equal(payload.status, "ready");
  assert.equal(payload.desktop_release.tag, manifest.tag);
  assert.match(urls[0], /per_page=100&page=1$/);
  assert.match(urls[1], /per_page=100&page=2$/);
  assert.match(urls[2], /desktop-release-manifest\.json$/);
});
