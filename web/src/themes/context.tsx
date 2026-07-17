import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { BUILTIN_THEMES, defaultTheme } from "./presets";
import {
  GENERATED_THEME_VARIANTS,
  generatedThemeNameForAppearance,
} from "./generated";
import { themeAppearance } from "./generate";
import {
  FONT_CHOICES,
  THEME_DEFAULT_FONT_ID,
  getFontChoice,
} from "./fonts";
import type { DashboardTheme, ThemeListEntry } from "./types";
import { api } from "@/lib/api";
import {
  DEFAULT_TERMINAL_PREFS,
  normalizeTerminalPrefs,
  terminalFontUrl,
  type TerminalFontSize,
  type TerminalPrefs,
} from "@/lib/terminal-schemes";
import {
  ThemeContext,
  type AppearancePref,
  type ContrastPref,
  type ThemeContextValue,
} from "./use-theme";

import {
  APPEARANCE_STORAGE_KEY,
  CONTRAST_STORAGE_KEY,
  FONT_STORAGE_KEY,
  LEGACY_FONT_STORAGE_KEY,
  LEGACY_STORAGE_KEY,
  STORAGE_KEY,
  TERMINAL_PREFS_STORAGE_KEY,
  appearanceForThemeMigration,
  applyTheme,
  canonicalizeThemeEntry,
  injectFontStylesheet,
  migrateThemeName,
  setActiveFontOverride,
} from "./apply";

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function ThemeProvider({ children }: { children: ReactNode }) {
  /** Name of the currently active theme (built-in id or user YAML name). */
  const [themeName, setThemeName] = useState<string>(() => {
    if (typeof window === "undefined") return "fabric-light";
    const stored =
      window.localStorage.getItem(STORAGE_KEY) ??
      window.localStorage.getItem(LEGACY_STORAGE_KEY) ??
      "fabric-light";
    const appearancePreference = window.localStorage.getItem(
      APPEARANCE_STORAGE_KEY,
    );
    const systemPrefersDark =
      appearancePreference === "system" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    const migrated = migrateThemeName(
      stored,
      appearanceForThemeMigration(appearancePreference, systemPrefersDark),
    );
    // Converge on the Fabric key/id in one pass while preserving a seamless
    // upgrade for users with an older browser preference.
    window.localStorage.setItem(STORAGE_KEY, migrated);
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    return migrated;
  });

  /** All selectable themes (shown in the picker). Starts with just the
   *  built-ins; the API call below merges in user themes. */
  const [availableThemes, setAvailableThemes] = useState<ThemeListEntry[]>(() =>
    Object.values(BUILTIN_THEMES).map((t) => ({
      name: t.name,
      label: t.label,
      description: t.description,
    })),
  );

  /** Full definitions for user themes keyed by name — the API provides
   *  these so custom YAMLs apply without a client-side stub. */
  const [userThemeDefs, setUserThemeDefs] = useState<
    Record<string, DashboardTheme>
  >({});

  /** Active font-override id (independent of theme). `THEME_DEFAULT_FONT_ID`
   *  = no override. Seeded from localStorage so it's applied flash-free. */
  const [fontId, setFontId] = useState<string>(() => {
    if (typeof window === "undefined") return THEME_DEFAULT_FONT_ID;
    const stored =
      window.localStorage.getItem(FONT_STORAGE_KEY) ??
      window.localStorage.getItem(LEGACY_FONT_STORAGE_KEY);
    const valid =
      stored && getFontChoice(stored) ? stored : THEME_DEFAULT_FONT_ID;
    window.localStorage.setItem(FONT_STORAGE_KEY, valid);
    window.localStorage.removeItem(LEGACY_FONT_STORAGE_KEY);
    setActiveFontOverride(valid);
    return valid;
  });

  /** Appearance preference. Unset storage infers from the persisted theme
   *  so the control reflects reality on first render (user YAML themes
   *  aren't loaded yet at init — they fall back to `dark` until then). */
  const [appearance, setAppearanceState] = useState<AppearancePref>(() => {
    if (typeof window === "undefined") return "light";
    const stored = window.localStorage.getItem(APPEARANCE_STORAGE_KEY);
    if (stored === "dark" || stored === "light" || stored === "system") {
      return stored;
    }
    const initialTheme =
      BUILTIN_THEMES[
        migrateThemeName(window.localStorage.getItem(STORAGE_KEY) ?? "fabric-light")
      ];
    return initialTheme ? themeAppearance(initialTheme) : "light";
  });

  /** Mirror for effects that must read the CURRENT preference without
   *  re-subscribing (the one-shot getThemes mount effect). */
  const appearanceRef = useRef(appearance);
  useEffect(() => {
    appearanceRef.current = appearance;
  }, [appearance]);

  /** Same mirror for the active theme name — the mount effect must compare
   *  against the CURRENT theme, not its first-render closure capture. */
  const themeNameRef = useRef(themeName);
  useEffect(() => {
    themeNameRef.current = themeName;
  }, [themeName]);

  /** Flipped once the user explicitly picks a theme or appearance in this
   *  session. The getThemes adoption below bails out when set, so a slow
   *  /themes response can never clobber a choice the user made while the
   *  request was in flight. */
  const userPickedRef = useRef(false);

  /** Contrast preference — swaps generated themes for their high-contrast
   *  variants; hand-authored presets ignore it. */
  const [contrast, setContrastState] = useState<ContrastPref>(() => {
    if (typeof window === "undefined") return "normal";
    return window.localStorage.getItem(CONTRAST_STORAGE_KEY) === "high"
      ? "high"
      : "normal";
  });

  /** Terminal appearance overrides (scheme / font / size). Seeded from
   *  localStorage so embedded terminals mount with the right palette;
   *  the server value adopted below is the cross-browser source of truth. */
  const [terminalPrefs, setTerminalPrefsState] = useState<TerminalPrefs>(() => {
    if (typeof window === "undefined") return DEFAULT_TERMINAL_PREFS;
    try {
      const raw = window.localStorage.getItem(TERMINAL_PREFS_STORAGE_KEY);
      return raw
        ? normalizeTerminalPrefs(JSON.parse(raw))
        : DEFAULT_TERMINAL_PREFS;
    } catch {
      return DEFAULT_TERMINAL_PREFS;
    }
  });

  /** Mirror for the setters (stable callbacks that merge patches without
   *  re-subscribing) and the mount adoption effect. */
  const terminalPrefsRef = useRef(terminalPrefs);
  useEffect(() => {
    terminalPrefsRef.current = terminalPrefs;
  }, [terminalPrefs]);

  /** Flipped when the user touches a terminal pref this session, so a slow
   *  server response can't clobber their in-flight choice (same guard as
   *  `userPickedRef` for themes). */
  const terminalPickedRef = useRef(false);

  // Resolve a theme name to a full DashboardTheme, falling back to default
  // only when neither a built-in nor a user theme is found. Generated
  // themes resolve through their contrast variants first (BUILTIN_THEMES
  // only holds their normal-contrast definitions for the picker).
  const resolveTheme = useCallback(
    (name: string): DashboardTheme => {
      const systemPrefersDark =
        appearance === "system" &&
        typeof window !== "undefined" &&
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches;
      const migrationAppearance = appearanceForThemeMigration(
        appearance,
        systemPrefersDark,
      );
      const canonicalName = migrateThemeName(name, migrationAppearance);
      const generated = GENERATED_THEME_VARIANTS[canonicalName];
      if (generated) return generated[contrast];
      return (
        BUILTIN_THEMES[canonicalName] ??
        userThemeDefs[canonicalName] ??
        defaultTheme
      );
    },
    [appearance, userThemeDefs, contrast],
  );

  // `system` appearance: follow prefers-color-scheme, swapping between the
  // generated dark/light pair. Local-only persistence — server `active`
  // adoption is skipped in system mode (see the getThemes effect below).
  useEffect(() => {
    if (appearance !== "system" || typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const next = generatedThemeNameForAppearance(
        mq.matches ? "dark" : "light",
      );
      setThemeName(next);
      window.localStorage.setItem(STORAGE_KEY, next);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [appearance]);

  // Apply the active theme (and re-assert the font override at its tail)
  // whenever the theme, the resolver, OR the font override changes. Folding
  // font into the same effect means clearing the override re-runs applyTheme,
  // which restores the theme's own font; setting it re-asserts the override.
  useEffect(() => {
    setActiveFontOverride(fontId);
    applyTheme(resolveTheme(themeName));
  }, [themeName, resolveTheme, fontId]);

  // Load server-side themes (built-ins + user YAMLs) once on mount.
  useEffect(() => {
    let cancelled = false;
    api
      .getThemes()
      .then((resp) => {
        if (cancelled) return;
        // Definitions the server shipped (user themes). Hoisted so the
        // adoption branch below can resolve the active theme against the
        // fresh defs — the userThemeDefs state hasn't flushed yet here.
        const defs: Record<string, DashboardTheme> = {};
        if (resp.themes?.length) {
          const canonicalEntries = resp.themes.map(canonicalizeThemeEntry);
          // Union client built-ins UNDER the server list: older backends
          // don't know about client-side presets (the generated pair), and
          // replacing the list outright would drop them from the picker.
          const merged = new Map<string, ThemeListEntry>();
          for (const t of Object.values(BUILTIN_THEMES)) {
            merged.set(t.name, {
              name: t.name,
              label: t.label,
              description: t.description,
            });
          }
          for (const entry of canonicalEntries) {
            merged.set(entry.name, entry);
          }
          setAvailableThemes(Array.from(merged.values()));
          for (const entry of canonicalEntries) {
            if (entry.definition) {
              defs[entry.name] = entry.definition;
            }
          }
          if (Object.keys(defs).length > 0) setUserThemeDefs(defs);
        }
        // In system mode the OS — not the server — owns the active theme;
        // adopting `resp.active` here would fight the matchMedia effect.
        // Likewise a theme/appearance the user picked while this request
        // was in flight outranks the (now stale) server value.
        if (
          resp.active &&
          !userPickedRef.current &&
          appearanceRef.current !== "system"
        ) {
          const migrationAppearance = appearanceForThemeMigration(
            appearanceRef.current,
          );
          let migratedActive = migrateThemeName(
            resp.active,
            migrationAppearance,
          );
          // The explicit light/dark preference owns which member of the
          // canonical pair is active. This also protects a local dark choice
          // when an older backend has already rewritten a heritage id to
          // `fabric-light` before returning the catalog.
          if (GENERATED_THEME_VARIANTS[migratedActive]) {
            migratedActive = generatedThemeNameForAppearance(
              migrationAppearance,
            );
          }
          if (migratedActive !== themeNameRef.current) {
            setThemeName(migratedActive);
            window.localStorage.setItem(STORAGE_KEY, migratedActive);
          }
          // Mirror setTheme(): adopting the server's active theme also pins
          // the appearance preference to that theme's native mode, so the
          // Appearance control stays truthful when the server flips the mode.
          const adopted =
            BUILTIN_THEMES[migratedActive] ??
            defs[migratedActive] ??
            defaultTheme;
          const native = themeAppearance(adopted);
          if (native !== appearanceRef.current) {
            setAppearanceState(native);
            window.localStorage.setItem(APPEARANCE_STORAGE_KEY, native);
          }
          // If the server is still persisting the stale key, push the
          // migrated value back so it converges too — otherwise every
          // future page load would re-trigger this branch.
          if (migratedActive !== resp.active) {
            api.setTheme(migratedActive).catch(() => {});
          }
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Load the server-persisted font override once on mount. The server is
  // the source of truth across browsers; localStorage just avoids the flash.
  useEffect(() => {
    let cancelled = false;
    api
      .getFontPref()
      .then((resp) => {
        if (cancelled) return;
        const serverId =
          resp?.font && getFontChoice(resp.font) ? resp.font : THEME_DEFAULT_FONT_ID;
        if (serverId !== fontId) {
          setFontId(serverId);
          if (typeof window !== "undefined") {
            window.localStorage.setItem(FONT_STORAGE_KEY, serverId);
          }
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load the server-persisted terminal prefs once on mount (same contract
  // as the font override: server wins across browsers, localStorage only
  // avoids the flash).
  useEffect(() => {
    let cancelled = false;
    api
      .getTerminalPref()
      .then((resp) => {
        if (cancelled || terminalPickedRef.current) return;
        const server = normalizeTerminalPrefs(resp);
        const current = terminalPrefsRef.current;
        if (
          server.scheme === current.scheme &&
          server.font === current.font &&
          server.size === current.size
        ) {
          return;
        }
        terminalPrefsRef.current = server;
        setTerminalPrefsState(server);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(
            TERMINAL_PREFS_STORAGE_KEY,
            JSON.stringify(server),
          );
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // A terminal font override is consumed by xterm as a plain CSS
  // font-family, so its webfont stylesheet must be present in the page for
  // the renderer to measure/rasterize it.
  useEffect(() => {
    injectFontStylesheet(terminalFontUrl(terminalPrefs.font));
  }, [terminalPrefs.font]);

  const updateTerminalPrefs = useCallback((patch: Partial<TerminalPrefs>) => {
    terminalPickedRef.current = true;
    const next = normalizeTerminalPrefs({
      ...terminalPrefsRef.current,
      ...patch,
    });
    terminalPrefsRef.current = next;
    setTerminalPrefsState(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(
        TERMINAL_PREFS_STORAGE_KEY,
        JSON.stringify(next),
      );
    }
    api.setTerminalPref(next).catch(() => {});
  }, []);

  const setTerminalScheme = useCallback(
    (id: string) => updateTerminalPrefs({ scheme: id }),
    [updateTerminalPrefs],
  );
  const setTerminalFont = useCallback(
    (id: string) => updateTerminalPrefs({ font: id }),
    [updateTerminalPrefs],
  );
  const setTerminalFontSize = useCallback(
    (size: TerminalFontSize) => updateTerminalPrefs({ size }),
    [updateTerminalPrefs],
  );

  const setTheme = useCallback(
    (name: string) => {
      userPickedRef.current = true;
      // Accept any name the server told us exists OR any built-in.
      const knownNames = new Set<string>([
        ...Object.keys(BUILTIN_THEMES),
        ...availableThemes.map((t) => t.name),
        ...Object.keys(userThemeDefs),
      ]);
      const canonicalName = migrateThemeName(
        name,
        appearanceForThemeMigration(appearance),
      );
      const next = knownNames.has(canonicalName) ? canonicalName : "fabric-light";
      setThemeName(next);
      // Picking a theme pins the appearance preference to that theme's
      // native mode (leaves `system` mode) so the picker stays truthful.
      const native = themeAppearance(resolveTheme(next));
      setAppearanceState(native);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, next);
        window.localStorage.setItem(APPEARANCE_STORAGE_KEY, native);
      }
      api.setTheme(next).catch(() => {});
    },
    [appearance, availableThemes, userThemeDefs, resolveTheme],
  );

  const setAppearance = useCallback(
    (pref: AppearancePref) => {
      userPickedRef.current = true;
      setAppearanceState(pref);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(APPEARANCE_STORAGE_KEY, pref);
      }
      if (pref === "system") return; // the matchMedia effect takes over
      // Explicit dark/light: keep the active theme when it already matches
      // (hand-authored presets keep their fixed appearance); otherwise swap
      // to the designated generated pair member.
      if (themeAppearance(resolveTheme(themeName)) === pref) return;
      const next = generatedThemeNameForAppearance(pref);
      setThemeName(next);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, next);
      }
      api.setTheme(next).catch(() => {});
    },
    [resolveTheme, themeName],
  );

  const setContrast = useCallback((pref: ContrastPref) => {
    setContrastState(pref);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(CONTRAST_STORAGE_KEY, pref);
    }
  }, []);

  const setFont = useCallback((id: string) => {
    const next = getFontChoice(id) ? id : THEME_DEFAULT_FONT_ID;
    setFontId(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(FONT_STORAGE_KEY, next);
    }
    api.setFontPref(next).catch(() => {});
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: resolveTheme(themeName),
      themeName,
      availableThemes,
      setTheme,
      fontId,
      fontChoices: FONT_CHOICES,
      setFont,
      appearance,
      setAppearance,
      contrast,
      setContrast,
      terminalPrefs,
      setTerminalScheme,
      setTerminalFont,
      setTerminalFontSize,
    }),
    [
      themeName,
      availableThemes,
      setTheme,
      resolveTheme,
      fontId,
      setFont,
      appearance,
      setAppearance,
      contrast,
      setContrast,
      terminalPrefs,
      setTerminalScheme,
      setTerminalFont,
      setTerminalFontSize,
    ],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

