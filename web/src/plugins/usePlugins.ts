/**
 * usePlugins hook — discovers and loads dashboard plugins.
 *
 * 1. Fetches plugin manifests from GET /api/dashboard/plugins
 * 2. Injects CSS <link> tags for plugins that declare css
 * 3. Loads plugin JS bundles via <script> tags
 * 4. Waits for plugins to call register() and resolves them
 */

import { useState, useEffect, useMemo, useRef } from "react";
import { useLocation } from "react-router-dom";
import { api, FABRIC_BASE_PATH } from "@/lib/api";
import { canonicalPluginTargetPath } from "@/app/routes";
import type { PluginManifest, RegisteredPlugin } from "./types";
import {
  getPluginComponent,
  onPluginRegistered,
  notifyPluginRegistry,
  setPluginLoadError,
} from "./registry";

export function usePlugins() {
  const { pathname } = useLocation();
  const [manifests, setManifests] = useState<PluginManifest[]>([]);
  const [plugins, setPlugins] = useState<RegisteredPlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const loadedScripts = useRef<Set<string>>(new Set());

  // Fetch manifests on mount.
  useEffect(() => {
    api
      .getPlugins()
      .then((list) => {
        setManifests(list);
        // Routes and override ownership are fully known once manifests arrive.
        // Individual PluginPage instances own their bundle loading UI, so a
        // slow optional bundle must never hold the persistent Chat host back.
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const assetManifests = useMemo(
    () => manifests.filter((manifest) => shouldLoadPluginAssets(manifest, pathname)),
    [manifests, pathname],
  );

  // Load plugin assets when manifests arrive.
  useEffect(() => {
    if (assetManifests.length === 0) return;

    const injectedScripts: HTMLScriptElement[] = [];

    for (const manifest of assetManifests) {
      // Inject CSS if specified.
      if (manifest.css) {
        const cssUrl = `${FABRIC_BASE_PATH}/dashboard-plugins/${manifest.name}/${manifest.css}`;
        if (!document.querySelector(`link[href="${cssUrl}"]`)) {
          const link = document.createElement("link");
          link.rel = "stylesheet";
          link.href = cssUrl;
          document.head.appendChild(link);
        }
      }

      // Load JS bundle. In dev, cache-bust so Vite HMR can clear the
      // in-memory registry while the browser would otherwise never
      // re-execute a previously cached <script> URL.
      const baseUrl = `${FABRIC_BASE_PATH}/dashboard-plugins/${manifest.name}/${manifest.entry}`;
      const scriptSrc = import.meta.env.DEV
        ? `${baseUrl}?fabric_dv=${Date.now()}`
        : baseUrl;
      if (!import.meta.env.DEV) {
        if (loadedScripts.current.has(baseUrl)) continue;
        loadedScripts.current.add(baseUrl);
      }

      const script = document.createElement("script");
      script.setAttribute("data-fabric-plugin", manifest.name);
      script.src = scriptSrc;
      script.async = true;
      // SRI integrity verification — defense against compromised plugin
      // delivery. Plugin manifests can declare an integrity hash
      // (e.g. "sha384-...") which the browser verifies before executing.
      // Without this, a man-in-the-middle or compromised plugin server
      // can substitute the JS bundle silently. Opt-in: when no integrity
      // is declared in the manifest, behavior is unchanged.
      if (manifest.integrity && typeof manifest.integrity === "string") {
        script.integrity = manifest.integrity;
        script.crossOrigin = "anonymous";
      }
      script.onerror = () => {
        setPluginLoadError(manifest.name, "LOAD_FAILED");
        console.warn(
          `[plugins] Failed to load ${manifest.name} from ${scriptSrc} (open Network tab)`,
        );
      };
      script.onload = () => {
        notifyPluginRegistry();
        queueMicrotask(() => {
          if (getPluginComponent(manifest.name)) return;
          setPluginLoadError(manifest.name, "NO_REGISTER");
        });
      };
      document.body.appendChild(script);
      injectedScripts.push(script);
    }

    return () => {
      if (import.meta.env.DEV) {
        for (const el of injectedScripts) {
          el.remove();
        }
      }
    };
  }, [assetManifests]);

  // Listen for plugin registrations and resolve them against manifests.
  useEffect(() => {
    function resolvePlugins() {
      const resolved: RegisteredPlugin[] = [];
      for (const manifest of manifests) {
        const component = getPluginComponent(manifest.name);
        if (component) {
          resolved.push({ manifest, component });
        }
      }
      setPlugins(resolved);
    }

    resolvePlugins();
    const unsub = onPluginRegistered(resolvePlugins);
    return unsub;
  }, [manifests]);

  return { plugins, manifests, loading };
}

function normalizedRoutePath(path: string): string {
  return path.replace(/\/+$/, "") || "/";
}

/**
 * Visible pages and declared slot providers remain eager. A hidden page-only
 * integration is fetched only when its canonical route, override, or alias is
 * actually open, keeping retired/admin-only bundles off the Chat startup path.
 */
export function shouldLoadPluginAssets(
  manifest: PluginManifest,
  pathname: string,
): boolean {
  if (!manifest.tab.hidden || (manifest.slots?.length ?? 0) > 0) return true;

  const current = canonicalPluginTargetPath(normalizedRoutePath(pathname));
  return [
    manifest.tab.path,
    manifest.tab.override,
    ...(manifest.tab.aliases ?? []),
  ].some((candidate) =>
    candidate
      ? canonicalPluginTargetPath(normalizedRoutePath(candidate)) === current
      : false,
  );
}
