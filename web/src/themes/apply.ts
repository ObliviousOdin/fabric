/**
 * Theme application — everything that turns a `DashboardTheme` into CSS
 * variables, injected stylesheets, and dataset attributes on `:root`.
 *
 * Lives outside `context.tsx` for two reasons: the provider file must
 * export only components (Fast Refresh), and `main.tsx` pre-applies the
 * persisted theme via `applyPersistedThemeEarly()` before the React tree
 * mounts so theme-overridden installs never flash the default palette.
 */

import {
  bestForeground,
  ensureContrast,
  isLightColor,
  oklchToHex,
  themeAppearance,
} from "./generate";
import {
  THEME_DEFAULT_FONT_ID,
  getFontChoice,
  type FontChoice,
} from "./fonts";
import { BUILTIN_THEMES } from "./presets";
import { GENERATED_THEME_VARIANTS, generatedThemeNameForAppearance } from "./generated";
import type {
  DashboardTheme,
  ThemeAssets,
  ThemeColorOverrides,
  ThemeComponentStyles,
  ThemeDensity,
  ThemeLayer,
  ThemeLayout,
  ThemeLayoutVariant,
  ThemeListEntry,
  ThemePalette,
  ThemeSeriesColors,
  ThemeTypography,
} from "./types";
import {
  DEFAULT_TERMINAL_BACKGROUND,
  DEFAULT_TERMINAL_FOREGROUND,
} from "@/lib/terminal-theme";

/** LocalStorage key — pre-applied before the React tree mounts to avoid
 *  a visible flash of the default palette on theme-overridden installs. */
export const STORAGE_KEY = "fabric-dashboard-theme";
export const LEGACY_STORAGE_KEY = "hermes-dashboard-theme";

/** LocalStorage key for the font override (independent of theme). Holds a
 *  font id from the catalog in `fonts.ts`, or the `THEME_DEFAULT_FONT_ID`
 *  sentinel / absent = "use the active theme's font". Pre-applied before
 *  the React tree mounts (see `main.tsx`) to avoid a font flash. */
export const FONT_STORAGE_KEY = "fabric-dashboard-font";
export const LEGACY_FONT_STORAGE_KEY = "hermes-dashboard-font";

/** LocalStorage key for the terminal preferences (color scheme, font,
 *  font size) applied to the embedded xterm terminals. Holds a JSON blob —
 *  see `themes/use-theme.ts` `TerminalPrefs`. Independent of the theme:
 *  the scheme pins an explicit ANSI palette (catalog in
 *  `lib/terminal-schemes.ts`) instead of deriving one from the theme. */
export const TERMINAL_PREFS_STORAGE_KEY = "fabric-dashboard-terminal";

/** LocalStorage key for the appearance preference (dark | light | system).
 *  `system` follows `prefers-color-scheme` and swaps between the generated
 *  dark/light pair; picking a hand-authored preset pins the preference to
 *  that preset's native mode. */
export const APPEARANCE_STORAGE_KEY = "fabric-appearance";

/** LocalStorage key for the contrast preference (normal | high). High
 *  contrast swaps the generated pair for their high-contrast variants;
 *  hand-authored presets are unaffected. */
export const CONTRAST_STORAGE_KEY = "fabric-contrast";

/** Legacy visual identities that now converge on the canonical generated
 *  Fabric pair. They remain accepted as migration inputs, but never appear
 *  in the picker or survive as the persisted active id. */
const HERITAGE_THEME_NAMES = new Set([
  "lens-5i",
  "nous-blue",
  "fabric-blue",
  "fabric-teal",
  "default-large",
]);

/** Renames of other built-in theme keys we've shipped previously. */
const THEME_NAME_ALIASES: Record<string, string> = {
  // The old generic id also converges on the canonical light baseline.
  default: "fabric-light",
};

export type ThemeMigrationAppearance = "dark" | "light";

/** Resolve a stored appearance preference to the generated pair member used
 *  during legacy-theme migration. Light is the safe default; system only
 *  selects dark when the current OS preference explicitly does. */
export function appearanceForThemeMigration(
  preference: string | null,
  systemPrefersDark = false,
): ThemeMigrationAppearance {
  return preference === "dark" ||
    (preference === "system" && systemPrefersDark)
    ? "dark"
    : "light";
}

export function migrateThemeName(
  name: string,
  appearance: ThemeMigrationAppearance = "light",
): string {
  if (HERITAGE_THEME_NAMES.has(name)) {
    return generatedThemeNameForAppearance(appearance);
  }
  return THEME_NAME_ALIASES[name] ?? name;
}

/** Canonicalise built-in theme metadata from older backends without ever
 *  surfacing their retired ids or labels in the picker. */
export function canonicalizeThemeEntry(entry: ThemeListEntry): ThemeListEntry {
  const name = migrateThemeName(entry.name);
  const builtin = BUILTIN_THEMES[name];
  if (builtin) {
    return {
      name: builtin.name,
      label: builtin.label,
      description: builtin.description,
    };
  }
  return {
    ...entry,
    name,
    definition: entry.definition ? { ...entry.definition, name } : undefined,
  };
}

/** Tracks fontUrls we've already injected so multiple theme switches don't
 *  pile up <link> tags. Keyed by URL. */
const INJECTED_FONT_URLS = new Set<string>();

// ---------------------------------------------------------------------------
// CSS variable builders
// ---------------------------------------------------------------------------

/** Turn a ThemeLayer into the two CSS expressions the DS consumes:
 *  `--<name>` (color-mix'd with alpha) and `--<name>-base` (opaque hex). */
function layerVars(
  name: "background" | "midground" | "foreground",
  layer: ThemeLayer,
): Record<string, string> {
  const pct = Math.round(layer.alpha * 100);
  return {
    [`--${name}`]: `color-mix(in srgb, ${layer.hex} ${pct}%, transparent)`,
    [`--${name}-base`]: layer.hex,
    [`--${name}-alpha`]: String(layer.alpha),
  };
}

function paletteVars(palette: ThemePalette): Record<string, string> {
  return {
    ...layerVars("background", palette.background),
    ...layerVars("midground", palette.midground),
    ...layerVars("foreground", palette.foreground),
  };
}

const DENSITY_MULTIPLIERS: Record<ThemeDensity, string> = {
  compact: "0.85",
  comfortable: "1",
  spacious: "1.2",
};

function typographyVars(typo: ThemeTypography): Record<string, string> {
  return {
    "--theme-font-sans": typo.fontSans,
    "--theme-font-mono": typo.fontMono,
    "--theme-font-display": typo.fontDisplay ?? typo.fontSans,
    "--theme-base-size": typo.baseSize,
    "--theme-line-height": typo.lineHeight,
    "--theme-letter-spacing": typo.letterSpacing,
  };
}

function layoutVars(layout: ThemeLayout): Record<string, string> {
  return {
    "--radius": layout.radius,
    "--theme-radius": layout.radius,
    "--theme-spacing-mul": DENSITY_MULTIPLIERS[layout.density] ?? "1",
    "--theme-density": layout.density,
  };
}

/** Map a color-overrides key (camelCase) to its `--color-*` CSS var. */
const OVERRIDE_KEY_TO_VAR: Record<keyof ThemeColorOverrides, string> = {
  card: "--color-card",
  cardForeground: "--color-card-foreground",
  popover: "--color-popover",
  popoverForeground: "--color-popover-foreground",
  primary: "--color-primary",
  primaryForeground: "--color-primary-foreground",
  secondary: "--color-secondary",
  secondaryForeground: "--color-secondary-foreground",
  muted: "--color-muted",
  mutedForeground: "--color-muted-foreground",
  accent: "--color-accent",
  accentForeground: "--color-accent-foreground",
  destructive: "--color-destructive",
  destructiveForeground: "--color-destructive-foreground",
  success: "--color-success",
  warning: "--color-warning",
  border: "--color-border",
  input: "--color-input",
  ring: "--color-ring",
};

/** The `@theme inline` bridge in index.css bakes `var(--theme-color-*, …)`
 *  chains into compiled utilities, so overrides must land on that slot;
 *  the plain `--color-*` copy keeps DS dist styles and plugin CSS that
 *  read the vars directly in sync. */
function themeOverrideVarFor(cssVar: string): string {
  return cssVar.replace(/^--color-/, "--theme-color-");
}

/** Keys we might have written on a previous theme — needed to know which
 *  properties to clear when a theme with fewer overrides replaces one
 *  with more. */
const ALL_OVERRIDE_VARS = Object.values(OVERRIDE_KEY_TO_VAR).flatMap((v) => [
  v,
  themeOverrideVarFor(v),
]);

function overrideVars(
  overrides: ThemeColorOverrides | undefined,
): Record<string, string> {
  if (!overrides) return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(overrides)) {
    if (!value) continue;
    const cssVar = OVERRIDE_KEY_TO_VAR[key as keyof ThemeColorOverrides];
    if (cssVar) {
      out[cssVar] = value;
      out[themeOverrideVarFor(cssVar)] = value;
    }
  }
  return out;
}

/** AA status tones for themes that don't pin their own. The bridge
 *  defaults (#be2323/#137d41/#876200) are tuned for the light canvas and
 *  fall to ~3:1 on dark presets, so any theme that omits a status
 *  override gets one derived against its actual background — the same
 *  fixed-hue recipe `generateTheme` uses (generate.ts status tones),
 *  with lightness matched to the theme's appearance. */
function deriveStatusFallbacks(theme: DashboardTheme): ThemeColorOverrides {
  const overrides = theme.colorOverrides ?? {};
  const bgHex = theme.palette.background.hex;
  const statusL = isLightColor(bgHex) ? 0.52 : 0.72;
  const status = (h: number, c: number): string =>
    oklchToHex(ensureContrast({ l: statusL, c, h }, bgHex, 4.5));
  const out: ThemeColorOverrides = {};
  if (!overrides.destructive) {
    out.destructive = status(27, 0.19);
    if (!overrides.destructiveForeground) {
      out.destructiveForeground = bestForeground(out.destructive);
    }
  }
  if (!overrides.success) out.success = status(152, 0.13);
  if (!overrides.warning) out.warning = status(83, 0.14);
  return out;
}

/** Map data-series accents to their CSS vars. Themes omit either field to
 *  inherit the `:root` default from `index.css`; when omitted we also
 *  proactively clear any leftover value from a previous theme so switches
 *  don't carry stale colors. */
const SERIES_KEY_TO_VAR: Record<keyof ThemeSeriesColors, string> = {
  inputTokenAccent: "--series-input-token",
  outputTokenAccent: "--series-output-token",
};

const ALL_SERIES_VARS = Object.values(SERIES_KEY_TO_VAR);

function seriesColorVars(
  series: ThemeSeriesColors | undefined,
): Record<string, string> {
  if (!series) return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(series)) {
    if (!value) continue;
    const cssVar = SERIES_KEY_TO_VAR[key as keyof ThemeSeriesColors];
    if (cssVar) out[cssVar] = value;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Asset + component-style + layout variant vars
// ---------------------------------------------------------------------------

/** Well-known named asset slots a theme may populate. Kept in sync with
 *  `_THEME_NAMED_ASSET_KEYS` in `fabric_cli/web_server.py`. */
const NAMED_ASSET_KEYS = ["bg", "hero", "logo", "crest", "sidebar", "header"] as const;

/** Component buckets mirrored from the backend's `_THEME_COMPONENT_BUCKETS`.
 *  Each bucket emits `--component-<bucket>-<kebab-prop>` CSS vars. */
const COMPONENT_BUCKETS = [
  "card", "header", "footer", "sidebar", "tab",
  "progress", "badge", "backdrop", "page",
] as const;

/** Camel → kebab (`clipPath` → `clip-path`). */
function toKebab(s: string): string {
  return s.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
}

/** Build `--theme-asset-*` CSS vars from the assets block. Values are wrapped
 *  in `url(...)` when they look like a bare path/URL; raw CSS expressions
 *  (`linear-gradient(...)`, pre-wrapped `url(...)`, `none`) pass through. */
function assetVars(assets: ThemeAssets | undefined): Record<string, string> {
  if (!assets) return {};
  const out: Record<string, string> = {};
  const wrap = (v: string): string => {
    const trimmed = v.trim();
    if (!trimmed) return "";
    // Already a CSS image/gradient/url/none — don't re-wrap.
    if (/^(url\(|linear-gradient|radial-gradient|conic-gradient|none$)/i.test(trimmed)) {
      return trimmed;
    }
    // Bare path / http(s) URL / data: URL → wrap in url().
    return `url("${trimmed.replace(/"/g, '\\"')}")`;
  };
  for (const key of NAMED_ASSET_KEYS) {
    const val = assets[key];
    if (typeof val === "string" && val.trim()) {
      out[`--theme-asset-${key}`] = wrap(val);
      out[`--theme-asset-${key}-raw`] = val;
    }
  }
  if (assets.custom) {
    for (const [key, val] of Object.entries(assets.custom)) {
      if (typeof val !== "string" || !val.trim()) continue;
      if (!/^[a-zA-Z0-9_-]+$/.test(key)) continue;
      out[`--theme-asset-custom-${key}`] = wrap(val);
      out[`--theme-asset-custom-${key}-raw`] = val;
    }
  }
  return out;
}

/** Build `--component-<bucket>-<prop>` CSS vars from the componentStyles
 *  block. Values pass through untouched so themes can use any CSS expression. */
function componentStyleVars(
  styles: ThemeComponentStyles | undefined,
): Record<string, string> {
  if (!styles) return {};
  const out: Record<string, string> = {};
  for (const bucket of COMPONENT_BUCKETS) {
    const props = (styles as Record<string, Record<string, string> | undefined>)[bucket];
    if (!props) continue;
    for (const [prop, value] of Object.entries(props)) {
      if (typeof value !== "string" || !value.trim()) continue;
      // Same guardrail as backend — camelCase or kebab-case alnum only.
      if (!/^[a-zA-Z0-9_-]+$/.test(prop)) continue;
      out[`--component-${bucket}-${toKebab(prop)}`] = value;
    }
  }
  return out;
}

// Tracks keys we set on the previous theme so we can clear them when the
// next theme has fewer assets / component vars. Without this, switching
// from a richly-decorated theme to a plain one would leave stale vars.
let _PREV_DYNAMIC_VAR_KEYS: Set<string> = new Set();

/** ID for the injected <style> tag that carries a theme's customCSS.
 *  A single tag is reused + replaced on every theme switch. */
const CUSTOM_CSS_STYLE_ID = "fabric-theme-custom-css";

function applyCustomCSS(css: string | undefined) {
  if (typeof document === "undefined") return;
  let el = document.getElementById(CUSTOM_CSS_STYLE_ID) as HTMLStyleElement | null;
  if (!css || !css.trim()) {
    if (el) el.remove();
    return;
  }
  if (!el) {
    el = document.createElement("style");
    el.id = CUSTOM_CSS_STYLE_ID;
    el.setAttribute("data-fabric-theme-css", "true");
    document.head.appendChild(el);
  }
  el.textContent = css;
}

function applyLayoutVariant(variant: ThemeLayoutVariant | undefined) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const final: ThemeLayoutVariant = variant ?? "standard";
  root.dataset.layoutVariant = final;
  root.style.setProperty("--theme-layout-variant", final);
}

// ---------------------------------------------------------------------------
// Font stylesheet injection
// ---------------------------------------------------------------------------

export function injectFontStylesheet(url: string | undefined) {
  if (!url || typeof document === "undefined") return;
  if (INJECTED_FONT_URLS.has(url)) return;
  // Also skip if the page already has this href (e.g. SSR'd or persisted).
  const existing = document.querySelector<HTMLLinkElement>(
    `link[rel="stylesheet"][href="${CSS.escape(url)}"]`,
  );
  if (existing) {
    INJECTED_FONT_URLS.add(url);
    return;
  }
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = url;
  link.setAttribute("data-fabric-theme-font", "true");
  document.head.appendChild(link);
  INJECTED_FONT_URLS.add(url);
}

// ---------------------------------------------------------------------------
// Font override (independent of theme)
// ---------------------------------------------------------------------------

/** The active font-override id, mirrored at module scope so `applyTheme`
 *  can re-assert it after every theme switch (theme application rewrites
 *  `--theme-font-sans`, so the override has to win again afterwards). */
let _ACTIVE_FONT_OVERRIDE: string = THEME_DEFAULT_FONT_ID;

/** Provider hook-point: records the active override id so `applyTheme`
 *  can re-assert it after each theme switch. */
export function setActiveFontOverride(fontId: string): void {
  _ACTIVE_FONT_OVERRIDE = fontId;
}

/** Apply (or clear) the font override on `:root`. When a catalog font is
 *  active we override `--theme-font-sans` and `--theme-font-display` and
 *  inject its webfont; the theme keeps ownership of `--theme-font-mono`
 *  (code/terminal) so picking a body font doesn't mangle code blocks.
 *  Passing the theme-default sentinel removes the override so the theme's
 *  own font shows through. */
export function applyFontOverride(fontId: string | undefined) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const choice: FontChoice | undefined = getFontChoice(fontId);
  if (!choice) {
    // Clear → fall back to whatever the active theme set (applyTheme already
    // wrote the theme's --theme-font-sans/-display before this runs).
    root.style.removeProperty("--theme-font-override-sans");
    return;
  }
  injectFontStylesheet(choice.fontUrl);
  // Set both the override marker var (used by the picker for diagnostics)
  // and the live consumed vars. We re-set the consumed vars directly so the
  // change is immediate and survives the next applyTheme via _ACTIVE_FONT_OVERRIDE.
  root.style.setProperty("--theme-font-override-sans", choice.stack);
  root.style.setProperty("--theme-font-sans", choice.stack);
  root.style.setProperty("--theme-font-display", choice.stack);
}

// ---------------------------------------------------------------------------
// Apply a full theme to :root
// ---------------------------------------------------------------------------

export function applyTheme(theme: DashboardTheme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = theme.name;
  root.dataset.appearance = themeAppearance(theme);

  // Clear any overrides from a previous theme before applying the new set.
  for (const cssVar of ALL_OVERRIDE_VARS) {
    root.style.removeProperty(cssVar);
  }
  // Same clear-then-set for series colors so a theme that defines them
  // doesn't leave its values behind when the user switches to a theme that
  // inherits the `:root` defaults.
  for (const cssVar of ALL_SERIES_VARS) {
    root.style.removeProperty(cssVar);
  }
  // Clear dynamic (asset/component) vars from the previous theme so the
  // new one starts clean — otherwise stale notched clip-paths, hero URLs,
  // etc. would bleed across theme switches.
  for (const prevKey of _PREV_DYNAMIC_VAR_KEYS) {
    root.style.removeProperty(prevKey);
  }

  const assetMap = assetVars(theme.assets);
  const componentMap = componentStyleVars(theme.componentStyles);
  _PREV_DYNAMIC_VAR_KEYS = new Set([
    ...Object.keys(assetMap),
    ...Object.keys(componentMap),
  ]);

  const vars = {
    ...paletteVars(theme.palette),
    ...typographyVars(theme.typography),
    ...layoutVars(theme.layout),
    ...overrideVars(deriveStatusFallbacks(theme)),
    ...overrideVars(theme.colorOverrides),
    ...seriesColorVars(theme.seriesColors),
    ...assetMap,
    ...componentMap,
  };
  for (const [k, v] of Object.entries(vars)) {
    root.style.setProperty(k, v);
  }

  injectFontStylesheet(theme.typography.fontUrl);
  applyCustomCSS(theme.customCSS);
  applyLayoutVariant(theme.layoutVariant);

  // Keep native form controls / scrollbars in step with the canvas — light
  // themes (Fabric Light and light YAML themes) would otherwise render dark
  // scrollbars against a light page.
  root.style.setProperty("color-scheme", themeAppearance(theme));

  // Terminal colors — read by ChatPage via useTheme(); also available as CSS vars.
  root.style.setProperty(
    "--theme-terminal-background",
    theme.terminalBackground ?? DEFAULT_TERMINAL_BACKGROUND,
  );
  root.style.setProperty(
    "--theme-terminal-foreground",
    theme.terminalForeground ?? DEFAULT_TERMINAL_FOREGROUND,
  );

  // Re-assert the font override last: theme application just rewrote
  // --theme-font-sans/-display, so an active override has to win again.
  applyFontOverride(_ACTIVE_FONT_OVERRIDE);
}

// ---------------------------------------------------------------------------
// Pre-mount bootstrap
// ---------------------------------------------------------------------------

/** Apply the persisted theme synchronously before the React tree mounts so
 *  theme-overridden installs never flash the default palette (the provider
 *  re-applies the full theme immediately after mount and stays the source
 *  of truth). User YAML themes can't resolve without the API — those
 *  installs keep the built-in fallback until the provider loads them. */
export function applyPersistedThemeEarly(): void {
  if (typeof document === "undefined") return;
  try {
    const appearancePref = window.localStorage.getItem(
      APPEARANCE_STORAGE_KEY,
    );
    const systemPrefersDark =
      appearancePref === "system" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    const migrationAppearance = appearanceForThemeMigration(
      appearancePref,
      systemPrefersDark,
    );
    let name = migrateThemeName(
      window.localStorage.getItem(STORAGE_KEY) ??
        window.localStorage.getItem(LEGACY_STORAGE_KEY) ??
        "fabric-light",
      migrationAppearance,
    );
    if (appearancePref === "system" && typeof window.matchMedia === "function") {
      name = generatedThemeNameForAppearance(migrationAppearance);
    }
    const contrast =
      window.localStorage.getItem(CONTRAST_STORAGE_KEY) === "high"
        ? "high"
        : "normal";
    const theme =
      GENERATED_THEME_VARIANTS[name]?.[contrast] ?? BUILTIN_THEMES[name];
    if (theme) applyTheme(theme);
  } catch {
    // Privacy mode / SSR — the provider applies the theme after mount.
  }
}
