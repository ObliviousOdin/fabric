/**
 * Generated theme engine — Linear-style: a handful of inputs (base hue,
 * accent, appearance, contrast, density) expand into a complete
 * `DashboardTheme`, including the 3-layer palette AND the full
 * shadcn-compat `colorOverrides` token set (card/popover/primary/secondary/
 * muted/accent/status/border/input/ring + foregrounds).
 *
 * All color math happens in OKLCH — perceptually uniform lightness makes
 * elevation a simple lightness ladder (background → card → popover → …).
 * The OKLCH ⇄ sRGB conversion is hand-rolled (Björn Ottosson's OKLab,
 * D65, standard matrices) so no new dependency is needed.
 *
 * Design constraints baked in ("terminal-grade minimalism"):
 *   - surfaces are chroma-clamped → monochrome layered surfaces
 *   - the ONE chromatic accent lands on `primary` / `ring` only
 *   - text lightness auto-adjusts until WCAG targets hold:
 *       body text on background  ≥ 4.5:1 (normal) / ≥ 7:1 (high contrast)
 *       muted text on card       ≥ 4.5:1 (both contrast levels)
 */

import type {
  DashboardTheme,
  ThemeColorOverrides,
  ThemeDensity,
} from "./types";

// ---------------------------------------------------------------------------
// Color primitives
// ---------------------------------------------------------------------------

/** sRGB triplet, each channel 0–1 (gamma-encoded unless stated otherwise). */
export interface Rgb {
  r: number;
  g: number;
  b: number;
}

/** OKLCH: perceptual lightness 0–1, chroma ≥ 0, hue in degrees. */
export interface Oklch {
  l: number;
  c: number;
  h: number;
}

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

/** Parse `#rgb` / `#rrggbb` into 0–1 channels. Throws on garbage input —
 *  generator inputs are developer-authored constants, not user data. */
export function hexToRgb(hex: string): Rgb {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`invalid hex color: ${hex}`);
  let s = m[1];
  if (s.length === 3) s = s.split("").map((ch) => ch + ch).join("");
  return {
    r: parseInt(s.slice(0, 2), 16) / 255,
    g: parseInt(s.slice(2, 4), 16) / 255,
    b: parseInt(s.slice(4, 6), 16) / 255,
  };
}

export function rgbToHex({ r, g, b }: Rgb): string {
  const to = (v: number) =>
    Math.round(clamp01(v) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

// -- sRGB transfer function (IEC 61966-2-1) ---------------------------------

function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function linearToSrgb(c: number): number {
  return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
}

// -- OKLab ⇄ linear sRGB (Ottosson's standard D65 matrices) ------------------

/** Gamma-encoded sRGB → OKLCH. */
export function rgbToOklch(rgb: Rgb): Oklch {
  const r = srgbToLinear(rgb.r);
  const g = srgbToLinear(rgb.g);
  const b = srgbToLinear(rgb.b);

  const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
  const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
  const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;

  const l_ = Math.cbrt(l);
  const m_ = Math.cbrt(m);
  const s_ = Math.cbrt(s);

  const L = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_;
  const a = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_;
  const bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_;

  const c = Math.sqrt(a * a + bb * bb);
  let h = (Math.atan2(bb, a) * 180) / Math.PI;
  if (h < 0) h += 360;
  return { l: L, c, h };
}

/** OKLCH → gamma-encoded sRGB. May land outside [0,1] — callers that need
 *  displayable colors go through `oklchToHex` / `clampChromaToGamut`. */
export function oklchToRgb({ l, c, h }: Oklch): Rgb {
  const hRad = (h * Math.PI) / 180;
  const a = c * Math.cos(hRad);
  const b = c * Math.sin(hRad);

  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;

  const l3 = l_ * l_ * l_;
  const m3 = m_ * m_ * m_;
  const s3 = s_ * s_ * s_;

  const r = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3;
  const g = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3;
  const bl = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3;

  return { r: linearToSrgb(r), g: linearToSrgb(g), b: linearToSrgb(bl) };
}

function inGamut(rgb: Rgb, eps = 0.0005): boolean {
  return (
    rgb.r >= -eps && rgb.r <= 1 + eps &&
    rgb.g >= -eps && rgb.g <= 1 + eps &&
    rgb.b >= -eps && rgb.b <= 1 + eps
  );
}

/** Reduce chroma (binary search) until the color fits the sRGB gamut.
 *  Lightness and hue are preserved — chroma is the only free variable,
 *  which keeps the perceived elevation step intact. */
export function clampChromaToGamut(lch: Oklch): Oklch {
  const l = clamp01(lch.l);
  const candidate = { ...lch, l };
  if (inGamut(oklchToRgb(candidate))) return candidate;
  let lo = 0;
  let hi = candidate.c;
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2;
    if (inGamut(oklchToRgb({ ...candidate, c: mid }))) lo = mid;
    else hi = mid;
  }
  return { ...candidate, c: lo };
}

export function hexToOklch(hex: string): Oklch {
  return rgbToOklch(hexToRgb(hex));
}

/** OKLCH → hex, gamut-clamped so the output is always displayable. */
export function oklchToHex(lch: Oklch): string {
  return rgbToHex(oklchToRgb(clampChromaToGamut(lch)));
}

// ---------------------------------------------------------------------------
// WCAG contrast
// ---------------------------------------------------------------------------

/** WCAG 2.x relative luminance of an sRGB color (0 = black, 1 = white). */
export function relativeLuminance(color: string | Rgb): number {
  const rgb = typeof color === "string" ? hexToRgb(color) : color;
  return (
    0.2126 * srgbToLinear(rgb.r) +
    0.7152 * srgbToLinear(rgb.g) +
    0.0722 * srgbToLinear(rgb.b)
  );
}

/** WCAG 2.x contrast ratio between two colors — 1:1 … 21:1. */
export function contrastRatio(a: string | Rgb, b: string | Rgb): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Whether a hex color reads as a light surface (drives `color-scheme`
 *  and the dark/light classification of hand-authored + YAML themes). */
export function isLightColor(hex: string): boolean {
  return relativeLuminance(hex) >= 0.5;
}

/** Native appearance of any theme — derived from its canvas color so
 *  hand-authored presets and user YAML themes classify without metadata. */
export function themeAppearance(theme: DashboardTheme): "dark" | "light" {
  return isLightColor(theme.palette.background.hex) ? "light" : "dark";
}

/**
 * Step a color's OKLCH lightness AWAY from `against` until the WCAG
 * contrast target is met. When lightness pins at 0/1 before the target is
 * reached, chroma is burned off so the color can converge on pure
 * black/white (the maximum achievable contrast). Pure function.
 */
export function ensureContrast(
  color: Oklch,
  againstHex: string,
  minRatio: number,
): Oklch {
  const dir = relativeLuminance(againstHex) < 0.5 ? 1 : -1;
  let cur: Oklch = { ...color, l: clamp01(color.l) };
  for (let i = 0; i < 500; i++) {
    if (contrastRatio(oklchToHex(cur), againstHex) >= minRatio) return cur;
    const nextL = cur.l + dir * 0.005;
    if (nextL >= 0 && nextL <= 1) {
      cur = { ...cur, l: nextL };
    } else if (cur.c > 0) {
      cur = { ...cur, l: clamp01(nextL), c: Math.max(0, cur.c - 0.01) };
    } else {
      break; // at pure black/white — nothing more to gain
    }
  }
  return cur;
}

/** Evenly-stepped lightness ramp for elevation surfaces. Negative steps
 *  descend (light appearance). Values clamp to [0, 1]. */
export function lightnessLadder(
  start: number,
  step: number,
  count: number,
): number[] {
  return Array.from({ length: count }, (_, i) => clamp01(start + step * i));
}

/** Pick the higher-contrast foreground (white/black) for a solid fill. */
export function bestForeground(hex: string): string {
  return contrastRatio(hex, "#ffffff") >= contrastRatio(hex, "#000000")
    ? "#ffffff"
    : "#000000";
}

// ---------------------------------------------------------------------------
// Generator
// ---------------------------------------------------------------------------

export type ThemeAppearance = "dark" | "light";
export type ThemeContrast = "normal" | "high";

export interface GenerateThemeInput {
  name: string;
  label: string;
  description: string;
  /** Hue source for the monochrome surface ramp — chroma is clamped hard,
   *  so only a whisper of this color survives into the surfaces. */
  base: string;
  /** THE single chromatic accent (primary buttons, ring, focus). */
  accent: string;
  appearance: ThemeAppearance;
  contrast?: ThemeContrast;
  density?: ThemeDensity;
  radius?: string;
}

/** Per-appearance/contrast tuning. Lightness values are OKLCH `L`;
 *  `step` is the elevation half-step unit fed to `lightnessLadder`. */
interface AppearanceSpec {
  bgL: number;
  step: number;
  borderDelta: number;
  textL: number;
  mutedTextL: number;
  statusL: number;
  surfaceChroma: number;
  textChroma: number;
  /** Body-text-on-background WCAG minimum (4.5 normal, 7 high). */
  bodyMin: number;
}

const SPECS: Record<ThemeAppearance, Record<ThemeContrast, AppearanceSpec>> = {
  dark: {
    normal: {
      bgL: 0.16, step: 0.032, borderDelta: 0.11,
      textL: 0.93, mutedTextL: 0.74, statusL: 0.72,
      surfaceChroma: 0.01, textChroma: 0.012, bodyMin: 4.5,
    },
    high: {
      bgL: 0.105, step: 0.038, borderDelta: 0.2,
      textL: 0.97, mutedTextL: 0.82, statusL: 0.78,
      surfaceChroma: 0.008, textChroma: 0.008, bodyMin: 7,
    },
  },
  light: {
    normal: {
      bgL: 0.985, step: -0.018, borderDelta: -0.13,
      textL: 0.24, mutedTextL: 0.46, statusL: 0.52,
      surfaceChroma: 0.006, textChroma: 0.01, bodyMin: 4.5,
    },
    high: {
      bgL: 0.997, step: -0.02, borderDelta: -0.24,
      textL: 0.13, mutedTextL: 0.36, statusL: 0.45,
      surfaceChroma: 0.004, textChroma: 0.008, bodyMin: 7,
    },
  },
};

/** Mirrors `DEFAULT_TYPOGRAPHY` in presets.ts (not imported — presets.ts
 *  consumes the generated presets, so importing back would be a cycle). */
const SYSTEM_SANS =
  'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const SYSTEM_MONO =
  'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace';

/** Derive the accent/foreground pair: nudge the accent until it clears the
 *  canvas at ≥ 3:1 (WCAG 1.4.11 non-text) and carries a ≥ 4.5:1 label. */
function deriveAccentPair(
  accentHex: string,
  bgHex: string,
): { color: string; foreground: string } {
  let acc = ensureContrast(hexToOklch(accentHex), bgHex, 3.0);
  let hex = oklchToHex(acc);
  let fg = bestForeground(hex);
  if (contrastRatio(hex, fg) < 4.5) {
    acc = ensureContrast(acc, fg, 4.5);
    hex = oklchToHex(acc);
    fg = bestForeground(hex);
  }
  return { color: hex, foreground: fg };
}

function accentGlow(hex: string): string {
  const { r, g, b } = hexToRgb(hex);
  const to255 = (v: number) => Math.round(v * 255);
  return `rgba(${to255(r)}, ${to255(g)}, ${to255(b)}, 0.3)`;
}

/**
 * Expand a few inputs into a complete `DashboardTheme`. Pure — safe to run
 * at module load to build shipped presets, and in tests to assert the
 * contrast guarantees hold for arbitrary inputs.
 */
export function generateTheme(input: GenerateThemeInput): DashboardTheme {
  const contrast: ThemeContrast = input.contrast ?? "normal";
  const spec = SPECS[input.appearance][contrast];

  const base = hexToOklch(input.base);
  const hue = base.h;
  const surfC = Math.min(base.c, spec.surfaceChroma);
  const surface = (l: number): string =>
    oklchToHex({ l: clamp01(l), c: surfC, h: hue });

  // Elevation ladder in half-steps of the spec unit:
  // background → card → secondary → popover → muted → hover(accent slot).
  const steps = lightnessLadder(spec.bgL, spec.step / 2, 7);
  const bgHex = surface(steps[0]);
  const cardHex = surface(steps[2]);
  const secondaryHex = surface(steps[3]);
  const popoverHex = surface(steps[4]);
  const mutedHex = surface(steps[5]);
  const hoverHex = surface(steps[6]);
  const borderHex = surface(spec.bgL + spec.borderDelta);

  // Body text: near-neutral with a whisper of the base hue, pushed until
  // it clears BOTH the canvas and the most elevated common surface.
  let text: Oklch = {
    l: spec.textL,
    c: Math.min(base.c, spec.textChroma),
    h: hue,
  };
  text = ensureContrast(text, bgHex, spec.bodyMin);
  text = ensureContrast(text, popoverHex, spec.bodyMin);
  const textHex = oklchToHex(text);

  // Muted text: guaranteed AA on the card surface (the strictest common
  // host — cards sit closer to the text's lightness than the canvas).
  const mutedText = ensureContrast(
    { l: spec.mutedTextL, c: Math.min(base.c, spec.textChroma), h: hue },
    cardHex,
    4.5,
  );
  const mutedTextHex = oklchToHex(mutedText);

  const accent = deriveAccentPair(input.accent, bgHex);

  // Status tones: fixed hues, lightness adjusted until they hold AA as
  // text on the canvas (`text-success` / `text-warning` / `text-destructive`).
  const status = (h: number, c: number): string =>
    oklchToHex(ensureContrast({ l: spec.statusL, c, h }, bgHex, 4.5));
  const destructive = status(27, 0.19);
  const success = status(152, 0.13);
  const warning = status(83, 0.14);

  // `Required<>` so a future ThemeColorOverrides key fails the build here
  // instead of silently falling through to the bridge default.
  const colorOverrides: Required<ThemeColorOverrides> = {
    card: cardHex,
    cardForeground: textHex,
    popover: popoverHex,
    popoverForeground: textHex,
    primary: accent.color,
    primaryForeground: accent.foreground,
    secondary: secondaryHex,
    secondaryForeground: textHex,
    muted: mutedHex,
    mutedForeground: mutedTextHex,
    accent: hoverHex,
    accentForeground: textHex,
    destructive,
    destructiveForeground: bestForeground(destructive),
    success,
    warning,
    border: borderHex,
    input: borderHex,
    ring: accent.color,
  };

  return {
    name: input.name,
    label: input.label,
    description: input.description,
    palette: {
      background: { hex: bgHex, alpha: 1 },
      // `--color-foreground` bridges to midground, so midground carries
      // the generated body-text color.
      midground: { hex: textHex, alpha: 1 },
      foreground: { hex: "#ffffff", alpha: 0 },
      warmGlow: accentGlow(accent.color),
      noiseOpacity: 0,
    },
    typography: {
      fontSans: SYSTEM_SANS,
      fontMono: SYSTEM_MONO,
      baseSize: "15px",
      lineHeight: "1.55",
      letterSpacing: "0",
    },
    layout: {
      radius: input.radius ?? "0.5rem",
      density: input.density ?? "comfortable",
    },
    colorOverrides,
    // Monochrome + one accent: neutral (text tone) input series, accent
    // output series — never a second chromatic accent.
    seriesColors: {
      inputTokenAccent: textHex,
      outputTokenAccent: accent.color,
    },
    swatchColors: [bgHex, textHex, accent.color],
    terminalBackground:
      input.appearance === "dark" ? surface(spec.bgL - 0.03) : bgHex,
    terminalForeground: textHex,
  };
}
