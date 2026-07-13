/**
 * Shipped generated presets — the designated dark/light pair the
 * appearance preference (dark | light | system) swaps between.
 *
 * Both are produced by `generateTheme` from the same two inputs: a
 * blue-cast neutral base (hue source for the monochrome surfaces) and the
 * Fabric blue accent (the single chromatic accent). High-contrast variants
 * share the SAME theme name — they're surfaced through the contrast
 * toggle in the theme picker, not as separate preset ids.
 *
 * Current backends list this pair in the built-in catalog; the provider also
 * unions client built-ins into the picker so the themes remain usable against
 * older compatible backends.
 */

import { generateTheme } from "./generate";
import type { ThemeAppearance, ThemeContrast } from "./generate";
import type { DashboardTheme } from "./types";

/** Near-black with a whisper of blue — contributes hue only; the
 *  generator clamps chroma and re-derives lightness per appearance.
 *  Hue-matched to the Fabric-blue accent (OKLCH H≈263) so even the
 *  monochrome surfaces read as the brand family. */
const FABRIC_BASE = "#101828";
/** Fabric blue — the single chromatic accent. Canonical brand primary,
 *  shared with the desktop app (--theme-primary / --ui-blue) and the
 *  fabric-blue preset. Carries white text at 5.74:1 and holds ≥3:1
 *  non-text on both generated canvases without generator nudging. */
const FABRIC_ACCENT = "#0053fd";

export const GENERATED_DARK_THEME = "fabric-dark";
export const GENERATED_LIGHT_THEME = "fabric-light";

export const fabricDarkTheme = generateTheme({
  name: GENERATED_DARK_THEME,
  label: "Fabric Dark",
  description: "Generated dark — monochrome surfaces, single Fabric-blue accent",
  base: FABRIC_BASE,
  accent: FABRIC_ACCENT,
  appearance: "dark",
});

export const fabricDarkHighContrastTheme = generateTheme({
  name: GENERATED_DARK_THEME,
  label: "Fabric Dark",
  description: "Generated dark — monochrome surfaces, single Fabric-blue accent",
  base: FABRIC_BASE,
  accent: FABRIC_ACCENT,
  appearance: "dark",
  contrast: "high",
});

export const fabricLightTheme = generateTheme({
  name: GENERATED_LIGHT_THEME,
  label: "Fabric Light",
  description: "Generated light — monochrome surfaces, single Fabric-blue accent",
  base: FABRIC_BASE,
  accent: FABRIC_ACCENT,
  appearance: "light",
});

export const fabricLightHighContrastTheme = generateTheme({
  name: GENERATED_LIGHT_THEME,
  label: "Fabric Light",
  description: "Generated light — monochrome surfaces, single Fabric-blue accent",
  base: FABRIC_BASE,
  accent: FABRIC_ACCENT,
  appearance: "light",
  contrast: "high",
});

/** Contrast variants per generated theme name. The provider resolves
 *  through this map (contrast pref picks the variant) BEFORE falling back
 *  to `BUILTIN_THEMES`, which holds the normal variants for the picker. */
export const GENERATED_THEME_VARIANTS: Record<
  string,
  Record<ThemeContrast, DashboardTheme>
> = {
  [GENERATED_DARK_THEME]: {
    normal: fabricDarkTheme,
    high: fabricDarkHighContrastTheme,
  },
  [GENERATED_LIGHT_THEME]: {
    normal: fabricLightTheme,
    high: fabricLightHighContrastTheme,
  },
};

export function isGeneratedTheme(name: string): boolean {
  return Object.prototype.hasOwnProperty.call(GENERATED_THEME_VARIANTS, name);
}

/** The designated pair member for an appearance — what the system
 *  listener and the explicit Dark/Light controls swap to. */
export function generatedThemeNameForAppearance(
  appearance: ThemeAppearance,
): string {
  return appearance === "dark" ? GENERATED_DARK_THEME : GENERATED_LIGHT_THEME;
}
