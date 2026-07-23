import React, { useEffect, useMemo, useState } from "react";
import Layout from "@theme/Layout";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";

import styles from "./download.module.css";

const REPOSITORY = "ObliviousOdin/fabric";
const RELEASES_API =
  "https://api.github.com/repos/ObliviousOdin/fabric/releases?per_page=10";
const MANIFEST_NAME = "desktop-release-manifest.json";
const TAG_RE =
  /^v20\d{2}\.(?:[1-9]|1[0-2])\.(?:[1-9]|[12]\d|3[01])(?:\.[2-9]\d*)?$/;
const SHA_RE = /^[0-9a-f]{40}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const VERSION_RE = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;

interface ReleaseFile {
  name: string;
  ext: string;
  arch: string;
  platform: "mac" | "win" | "linux";
  size: number;
  sha256: string;
  url: string;
}

interface DesktopRelease {
  tag: string;
  html_url: string;
  published_at: string | null;
  desktop_app_version: string;
  source_sha: string;
  files: ReleaseFile[];
  combined_checksums_url: string;
}

interface LatestReleasePayload {
  schema_version: 1;
  status: "ready" | "unavailable";
  generated_at: string;
  newest_release_tag: string | null;
  publishing: boolean;
  desktop_release: DesktopRelease | null;
  message: string | null;
}

interface GitHubRelease {
  tag_name: string;
  draft: boolean;
  prerelease: boolean;
  published_at?: string;
  assets?: Array<{ name?: string }>;
}

function releaseAssetUrl(tag: string, name: string): string {
  if (!TAG_RE.test(tag) || name !== name.split(/[\\/]/).pop()) {
    throw new Error("Invalid release asset.");
  }
  return `https://github.com/${REPOSITORY}/releases/download/${encodeURIComponent(tag)}/${encodeURIComponent(name)}`;
}

function normalizeManifest(raw: unknown, release: GitHubRelease): DesktopRelease {
  const manifest = raw as Record<string, unknown>;
  if (
    !manifest ||
    manifest.repository !== REPOSITORY ||
    manifest.tag !== release.tag_name ||
    !TAG_RE.test(String(manifest.tag || "")) ||
    !SHA_RE.test(String(manifest.source_sha || "")) ||
    !VERSION_RE.test(String(manifest.desktop_app_version || "")) ||
    !Array.isArray(manifest.files)
  ) {
    throw new Error("The desktop release manifest is invalid.");
  }

  const version = String(manifest.desktop_app_version);
  const names = new Set<string>();
  const files = manifest.files.map((rawFile) => {
    const file = rawFile as Record<string, unknown>;
    const name = String(file?.name || "");
    const platform = String(file?.platform || "");
    const ext = String(file?.ext || "");
    const arch = String(file?.arch || "");
    const expected = `Fabric-${version}-${platform}-${arch}.${ext}`;
    if (
      name !== name.split(/[\\/]/).pop() ||
      name !== expected ||
      names.has(name) ||
      !["mac", "win", "linux"].includes(platform) ||
      !Number.isSafeInteger(Number(file.size)) ||
      Number(file.size) <= 0 ||
      !SHA256_RE.test(String(file.sha256 || ""))
    ) {
      throw new Error("The desktop release contains an invalid file.");
    }
    names.add(name);
    return {
      name,
      platform: platform as ReleaseFile["platform"],
      ext,
      arch,
      size: Number(file.size || 0),
      sha256: String(file.sha256 || ""),
      url: releaseAssetUrl(release.tag_name, name),
    };
  });

  return {
    tag: release.tag_name,
    html_url: `https://github.com/${REPOSITORY}/releases/tag/${encodeURIComponent(release.tag_name)}`,
    published_at: release.published_at || null,
    desktop_app_version: version,
    source_sha: String(manifest.source_sha),
    files,
    combined_checksums_url: releaseAssetUrl(
      release.tag_name,
      "SHA256SUMS-desktop.txt",
    ),
  };
}

async function fetchJson(url: string): Promise<unknown> {
  const response = await fetch(url, {
    headers: { accept: "application/vnd.github+json" },
  });
  if (!response.ok) {
    const limited =
      response.status === 403 &&
      response.headers.get("x-ratelimit-remaining") === "0";
    throw new Error(
      limited
        ? "GitHub’s public API rate limit is temporarily exhausted."
        : `Release lookup failed (HTTP ${response.status}).`,
    );
  }
  return response.json();
}

async function fetchLiveRelease(): Promise<LatestReleasePayload> {
  const raw = await fetchJson(RELEASES_API);
  if (!Array.isArray(raw)) throw new Error("GitHub returned an invalid response.");
  const releases = (raw as GitHubRelease[]).filter(
    (release) =>
      release &&
      !release.draft &&
      !release.prerelease &&
      typeof release.tag_name === "string",
  );
  const newest = releases[0]?.tag_name || null;
  for (const release of releases) {
    if (!release.assets?.some((asset) => asset.name === MANIFEST_NAME)) continue;
    const desktopRelease = normalizeManifest(
      await fetchJson(releaseAssetUrl(release.tag_name, MANIFEST_NAME)),
      release,
    );
    const publishing = Boolean(newest && newest !== desktopRelease.tag);
    return {
      schema_version: 1,
      status: "ready",
      generated_at: new Date().toISOString(),
      newest_release_tag: newest,
      publishing,
      desktop_release: desktopRelease,
      message: publishing
        ? `Desktop installers for ${newest} are still publishing; showing ${desktopRelease.tag}.`
        : null,
    };
  }
  return {
    schema_version: 1,
    status: "unavailable",
    generated_at: new Date().toISOString(),
    newest_release_tag: newest,
    publishing: Boolean(newest),
    desktop_release: null,
    message: newest
      ? `Desktop installers for ${newest} are still publishing.`
      : "No desktop installer release is available yet.",
  };
}

function fileFor(
  release: DesktopRelease,
  platform: ReleaseFile["platform"],
  ext: string,
): ReleaseFile | undefined {
  return release.files.find(
    (file) => file.platform === platform && file.ext === ext,
  );
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return "";
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function DownloadButton({
  file,
  label,
  primary = false,
}: {
  file: ReleaseFile | undefined;
  label: string;
  primary?: boolean;
}) {
  if (!file) return null;
  return (
    <a
      className={`button ${primary ? "button--primary" : "button--secondary"} button--lg`}
      href={file.url}
    >
      {label} <span className={styles.size}>{formatBytes(file.size)}</span>
    </a>
  );
}

export default function DownloadPage(): React.ReactElement {
  const staticReleaseUrl = useBaseUrl("/api/latest-release.json");
  const [payload, setPayload] = useState<LatestReleasePayload | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch(staticReleaseUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((value: LatestReleasePayload) => {
        if (active && value?.schema_version === 1) setPayload(value);
      })
      .catch(() => undefined)
      .finally(() => {
        void fetchLiveRelease()
          .then((value) => {
            if (active) {
              setPayload(value);
              setRefreshError(null);
            }
          })
          .catch((error: unknown) => {
            if (active)
              setRefreshError(
                error instanceof Error ? error.message : String(error),
              );
          });
      });
    return () => {
      active = false;
    };
  }, [staticReleaseUrl]);

  const release = payload?.desktop_release || null;
  const files = useMemo(
    () =>
      release
        ? {
            dmg: fileFor(release, "mac", "dmg"),
            zip: fileFor(release, "mac", "zip"),
            exe: fileFor(release, "win", "exe"),
            msi: fileFor(release, "win", "msi"),
            appImage: fileFor(release, "linux", "AppImage"),
            deb: fileFor(release, "linux", "deb"),
            rpm: fileFor(release, "linux", "rpm"),
          }
        : null,
    [release],
  );

  return (
    <Layout
      title="Download Fabric Desktop"
      description="Download Fabric Desktop for macOS, Windows, and Linux from the official Fabric GitHub Release."
    >
      <main className={styles.page}>
        <section className={styles.hero}>
          <p className={styles.eyebrow}>Fabric Desktop</p>
          <h1>Install your agent where you work.</h1>
          <p>
            Native desktop apps for macOS, Windows, and Linux, published from the
            same source as the Fabric CLI and backed by release checksums.
          </p>
          {release && (
            <div className={styles.releaseMeta}>
              Desktop {release.desktop_app_version} ·{" "}
              <a href={release.html_url}>{release.tag}</a> · source{" "}
              <code>{release.source_sha.slice(0, 12)}</code>
            </div>
          )}
        </section>

        {(payload?.message || refreshError) && (
          <div className={styles.notice} role="status">
            {payload?.message}
            {payload?.message && refreshError ? " " : ""}
            {refreshError && release
              ? `Live refresh failed; showing the last published snapshot. ${refreshError}`
              : refreshError}
          </div>
        )}

        {!release || !files ? (
          <section className={styles.empty}>
            <h2>Desktop installers are publishing</h2>
            <p>
              The release pipeline has not attached a complete installer
              manifest yet. You can install Fabric from source in the meantime.
            </p>
            <Link
              className="button button--primary"
              to="/getting-started/installation"
            >
              Install from source
            </Link>
          </section>
        ) : (
          <section className={styles.grid} aria-label="Desktop downloads">
            <article className={styles.card}>
              <div>
                <p className={styles.platform}>macOS</p>
                <h2>Apple silicon</h2>
                <p>M1 or later · signed and notarized</p>
              </div>
              <div className={styles.actions}>
                <DownloadButton file={files.dmg} label="Download DMG" primary />
                <DownloadButton file={files.zip} label="ZIP archive" />
              </div>
              <p className={styles.detail}>
                Open the DMG, drag Fabric to Applications, then accept Apple’s
                standard first-open confirmation. Intel Mac?{" "}
                <Link to="/getting-started/installation">Install from source</Link>.
              </p>
            </article>

            <article className={styles.card}>
              <div>
                <p className={styles.platform}>Windows</p>
                <h2>Windows 10/11 x64</h2>
                <p>NSIS installer · currently unsigned</p>
              </div>
              <div className={styles.actions}>
                <DownloadButton file={files.exe} label="Download EXE" primary />
                <DownloadButton file={files.msi} label="MSI package" />
              </div>
              <p className={styles.warning}>
                SmartScreen may show “Windows protected your PC.” Verify the
                SHA-256 checksum first, then choose <strong>More info → Run anyway</strong>{" "}
                only for this official download.
              </p>
            </article>

            <article className={styles.card}>
              <div>
                <p className={styles.platform}>Linux</p>
                <h2>Linux x86_64</h2>
                <p>Portable and package-manager formats</p>
              </div>
              <div className={styles.actions}>
                <DownloadButton
                  file={files.appImage}
                  label="Download AppImage"
                  primary
                />
                <DownloadButton file={files.deb} label="DEB" />
                <DownloadButton file={files.rpm} label="RPM" />
              </div>
              <p className={styles.detail}>
                Make the AppImage executable, or install the DEB/RPM with your
                distribution’s package manager.
              </p>
            </article>
          </section>
        )}

        {release && (
          <section className={styles.integrity}>
            <div>
              <p className={styles.eyebrow}>Trust, then run</p>
              <h2>Verify your download</h2>
              <p>
                Every installer is bound to the release manifest by SHA-256.
                Download the combined checksum file or use the per-platform file
                attached to the release.
              </p>
            </div>
            <div className={styles.integrityActions}>
              <a
                className="button button--secondary"
                href={release.combined_checksums_url}
              >
                SHA256SUMS-desktop.txt
              </a>
              <Link to="/user-guide/install-desktop">Installation guide</Link>
            </div>
          </section>
        )}

        <section className={styles.updateNote}>
          <h2>Updates stay aligned</h2>
          <p>
            Fabric Desktop checks the official release manifest. Clicking{" "}
            <strong>Update now</strong> downloads the matching installer; after
            you install and relaunch it, Fabric aligns its managed CLI/backend to
            that desktop release’s exact source revision before starting. Source
            installs keep the existing source updater, and remote backends remain
            independently updatable.
          </p>
        </section>
      </main>
    </Layout>
  );
}
