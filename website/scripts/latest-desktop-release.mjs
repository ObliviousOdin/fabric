import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const REPOSITORY = "ObliviousOdin/fabric";
const RELEASES_API = `https://api.github.com/repos/${REPOSITORY}/releases`;
const RELEASES_PAGE_SIZE = 100;
const PUBLISHED_FALLBACK =
  "https://obliviousodin.github.io/fabric/api/latest-release.json";
const MANIFEST_NAME = "desktop-release-manifest.json";
const TAG_RE =
  /^v20\d{2}\.(?:[1-9]|1[0-2])\.(?:[1-9]|[12]\d|3[01])(?:\.[2-9]\d*)?$/;
const VERSION_RE = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;
const SHA_RE = /^[0-9a-f]{40}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;

function unavailable(message, generatedAt = new Date().toISOString()) {
  return {
    schema_version: 1,
    status: "unavailable",
    generated_at: generatedAt,
    newest_release_tag: null,
    publishing: false,
    desktop_release: null,
    message,
  };
}

export function releaseAssetUrl(tag, name) {
  if (!TAG_RE.test(tag) || name !== name.split(/[\\/]/).pop()) {
    throw new Error("Invalid release tag or asset name.");
  }
  return `https://github.com/${REPOSITORY}/releases/download/${encodeURIComponent(tag)}/${encodeURIComponent(name)}`;
}

export function validateDesktopManifest(raw) {
  if (
    !raw ||
    raw.schema_version !== 1 ||
    raw.repository !== REPOSITORY ||
    !TAG_RE.test(raw.tag || "") ||
    !SHA_RE.test(raw.source_sha || "") ||
    !VERSION_RE.test(raw.desktop_app_version || "") ||
    !Array.isArray(raw.files)
  ) {
    throw new Error("Invalid desktop release manifest.");
  }

  const names = new Set();
  const files = raw.files.map((file) => {
    if (
      !file ||
      typeof file.name !== "string" ||
      file.name !== file.name.split(/[\\/]/).pop() ||
      !["mac", "win", "linux"].includes(file.platform) ||
      typeof file.ext !== "string" ||
      typeof file.arch !== "string" ||
      !Number.isSafeInteger(file.size) ||
      file.size <= 0 ||
      !SHA256_RE.test(file.sha256 || "")
    ) {
      throw new Error("Invalid desktop release file.");
    }
    const expected = `Fabric-${raw.desktop_app_version}-${file.platform}-${file.arch}.${file.ext}`;
    if (file.name !== expected || names.has(file.name)) {
      throw new Error("Unexpected or duplicate desktop release file.");
    }
    names.add(file.name);
    return {
      name: file.name,
      ext: file.ext,
      arch: file.arch,
      platform: file.platform,
      size: file.size,
      sha256: file.sha256,
      url: releaseAssetUrl(raw.tag, file.name),
    };
  });

  if (!files.length) {
    throw new Error("Desktop release manifest contains no files.");
  }

  return {
    schema_version: 1,
    repository: REPOSITORY,
    tag: raw.tag,
    source_sha: raw.source_sha,
    desktop_app_version: raw.desktop_app_version,
    platforms: Array.isArray(raw.platforms) ? raw.platforms : [],
    files,
  };
}

export async function resolveLatestDesktopRelease(
  releases,
  loadManifest,
  generatedAt = new Date().toISOString(),
) {
  if (!Array.isArray(releases)) {
    throw new Error("GitHub returned an invalid releases response.");
  }
  const published = releases.filter(
    (release) =>
      release &&
      !release.draft &&
      !release.prerelease &&
      typeof release.tag_name === "string",
  );
  const newestReleaseTag = published[0]?.tag_name || null;

  for (const release of published) {
    const assets = Array.isArray(release.assets) ? release.assets : [];
    const manifestAsset = assets.find((asset) => asset?.name === MANIFEST_NAME);
    if (!manifestAsset) continue;

    const manifest = validateDesktopManifest(
      await loadManifest(manifestAsset, release),
    );
    if (manifest.tag !== release.tag_name) {
      throw new Error("Desktop manifest tag does not match its GitHub Release.");
    }

    return {
      schema_version: 1,
      status: "ready",
      generated_at: generatedAt,
      newest_release_tag: newestReleaseTag,
      publishing: Boolean(newestReleaseTag && newestReleaseTag !== manifest.tag),
      desktop_release: {
        tag: manifest.tag,
        html_url: `https://github.com/${REPOSITORY}/releases/tag/${encodeURIComponent(manifest.tag)}`,
        published_at: release.published_at || null,
        desktop_app_version: manifest.desktop_app_version,
        source_sha: manifest.source_sha,
        files: manifest.files,
        combined_checksums_url: releaseAssetUrl(
          manifest.tag,
          "SHA256SUMS-desktop.txt",
        ),
      },
      message:
        newestReleaseTag && newestReleaseTag !== manifest.tag
          ? `Desktop installers for ${newestReleaseTag} are still publishing; showing ${manifest.tag}.`
          : null,
    };
  }

  return unavailable(
    newestReleaseTag
      ? `Desktop installers for ${newestReleaseTag} are still publishing.`
      : "No desktop installer release is available yet.",
    generatedAt,
  );
}

async function fetchJson(fetchImpl, url, token) {
  const headers = {
    accept: "application/vnd.github+json",
    "user-agent": "Fabric-Docs",
  };
  if (token) headers.authorization = `Bearer ${token}`;
  const response = await fetchImpl(url, { headers });
  if (!response.ok) {
    const rateLimited =
      response.status === 403 &&
      response.headers?.get?.("x-ratelimit-remaining") === "0";
    throw new Error(
      rateLimited ? "GitHub API rate limit reached." : `HTTP ${response.status}`,
    );
  }
  return response.json();
}

export async function fetchLatestDesktopRelease({
  fetchImpl = fetch,
  token = process.env.GITHUB_TOKEN || "",
} = {}) {
  const releases = [];
  for (let page = 1; ; page += 1) {
    const batch = await fetchJson(
      fetchImpl,
      `${RELEASES_API}?per_page=${RELEASES_PAGE_SIZE}&page=${page}`,
      token,
    );
    if (!Array.isArray(batch)) {
      throw new Error("GitHub returned an invalid releases response.");
    }
    releases.push(...batch);

    const payload = await resolveLatestDesktopRelease(
      releases,
      async (_asset, release) =>
        fetchJson(
          fetchImpl,
          releaseAssetUrl(release.tag_name, MANIFEST_NAME),
          token,
        ),
    );
    if (payload.status === "ready" || batch.length < RELEASES_PAGE_SIZE) {
      return payload;
    }
  }
}

export async function writeLatestDesktopRelease({
  outputFile,
  fetchImpl = fetch,
  token = process.env.GITHUB_TOKEN || "",
} = {}) {
  let payload;
  try {
    payload = await fetchLatestDesktopRelease({ fetchImpl, token });
  } catch (githubError) {
    try {
      const response = await fetchImpl(PUBLISHED_FALLBACK, {
        headers: { accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const fallback = await response.json();
      if (fallback?.schema_version !== 1) {
        throw new Error("published fallback schema is invalid");
      }
      payload = fallback;
      console.warn(
        `[prebuild] latest desktop release GitHub fetch failed (${githubError}); using published fallback.`,
      );
    } catch (fallbackError) {
      payload = unavailable(
        `Desktop release lookup is temporarily unavailable: ${githubError}`,
      );
      console.warn(
        `[prebuild] latest desktop release fallback failed (${fallbackError}); writing unavailable payload.`,
      );
    }
  }

  mkdirSync(dirname(outputFile), { recursive: true });
  writeFileSync(outputFile, `${JSON.stringify(payload, null, 2)}\n`);
  console.log(
    `[prebuild] wrote latest desktop release payload (${payload.status})`,
  );
  return payload;
}

export { MANIFEST_NAME, RELEASES_API, RELEASES_PAGE_SIZE };
