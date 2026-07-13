import { describe, expect, it } from "vitest";
import {
  bestForeground,
  clampChromaToGamut,
  contrastRatio,
  ensureContrast,
  generateTheme,
  hexToOklch,
  hexToRgb,
  isLightColor,
  lightnessLadder,
  oklchToHex,
  oklchToRgb,
  relativeLuminance,
  rgbToHex,
  themeAppearance,
} from "./generate";
import {
  fabricDarkHighContrastTheme,
  fabricDarkTheme,
  fabricLightHighContrastTheme,
  fabricLightTheme,
} from "./generated";
import type { DashboardTheme, ThemeColorOverrides } from "./types";

const HEX = /^#[0-9a-f]{6}$/;

// ---------------------------------------------------------------------------
// Color math
// ---------------------------------------------------------------------------

describe("hex <-> rgb", () => {
  it("parses 6- and 3-digit hex", () => {
    expect(hexToRgb("#ffffff")).toEqual({ r: 1, g: 1, b: 1 });
    expect(hexToRgb("#000000")).toEqual({ r: 0, g: 0, b: 0 });
    expect(hexToRgb("#fff")).toEqual({ r: 1, g: 1, b: 1 });
    expect(hexToRgb("0f0")).toEqual({ r: 0, g: 1, b: 0 });
  });

  it("throws on garbage", () => {
    expect(() => hexToRgb("teal")).toThrow();
    expect(() => hexToRgb("#12345")).toThrow();
  });

  it("round-trips", () => {
    for (const hex of ["#041c1c", "#ffe6cb", "#14b8a6", "#0053fd", "#808080"]) {
      expect(rgbToHex(hexToRgb(hex))).toBe(hex);
    }
  });
});

describe("sRGB <-> OKLCH", () => {
  it("maps white/black to the lightness extremes with ~zero chroma", () => {
    const white = hexToOklch("#ffffff");
    expect(white.l).toBeCloseTo(1, 3);
    expect(white.c).toBeLessThan(0.001);
    const black = hexToOklch("#000000");
    expect(black.l).toBeCloseTo(0, 3);
    expect(black.c).toBeLessThan(0.001);
  });

  it("round-trips within 1/255 per channel", () => {
    for (const hex of [
      "#041c1c", "#ffe6cb", "#14b8a6", "#fb2c36", "#0053fd",
      "#e8f2fd", "#101b1a", "#ffbd38", "#4ade80", "#777777",
    ]) {
      const back = oklchToRgb(hexToOklch(hex));
      const orig = hexToRgb(hex);
      expect(Math.abs(back.r - orig.r)).toBeLessThan(1 / 255);
      expect(Math.abs(back.g - orig.g)).toBeLessThan(1 / 255);
      expect(Math.abs(back.b - orig.b)).toBeLessThan(1 / 255);
    }
  });

  it("clamps out-of-gamut chroma while preserving lightness and hue", () => {
    const wild = { l: 0.5, c: 0.4, h: 30 };
    const clamped = clampChromaToGamut(wild);
    expect(clamped.l).toBe(0.5);
    expect(clamped.h).toBe(30);
    expect(clamped.c).toBeLessThan(0.4);
    const rgb = oklchToRgb(clamped);
    for (const ch of [rgb.r, rgb.g, rgb.b]) {
      expect(ch).toBeGreaterThanOrEqual(-0.001);
      expect(ch).toBeLessThanOrEqual(1.001);
    }
    expect(oklchToHex(wild)).toMatch(HEX);
  });
});

describe("WCAG contrast", () => {
  it("relative luminance of white is 1 and black is 0", () => {
    expect(relativeLuminance("#ffffff")).toBeCloseTo(1, 5);
    expect(relativeLuminance("#000000")).toBeCloseTo(0, 5);
  });

  it("black-on-white is 21:1 and symmetric", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 2);
    expect(contrastRatio("#ffffff", "#000000")).toBeCloseTo(21, 2);
  });

  it("identical colors are 1:1", () => {
    expect(contrastRatio("#14b8a6", "#14b8a6")).toBeCloseTo(1, 5);
  });

  it("classifies light and dark canvases", () => {
    expect(isLightColor("#e8f2fd")).toBe(true);
    expect(isLightColor("#ffffff")).toBe(true);
    expect(isLightColor("#041c1c")).toBe(false);
    expect(isLightColor("#101b1a")).toBe(false);
  });

  it("picks the higher-contrast foreground for a fill", () => {
    expect(bestForeground("#000000")).toBe("#ffffff");
    expect(bestForeground("#ffffff")).toBe("#000000");
  });
});

describe("ensureContrast", () => {
  it("raises a mid gray to AA against a dark canvas by lightening", () => {
    const start = { l: 0.4, c: 0.01, h: 180 };
    const fixed = ensureContrast(start, "#101b1a", 4.5);
    expect(fixed.l).toBeGreaterThan(start.l);
    expect(contrastRatio(oklchToHex(fixed), "#101b1a")).toBeGreaterThanOrEqual(4.5);
  });

  it("raises a mid gray to AAA against a light canvas by darkening", () => {
    const start = { l: 0.6, c: 0.01, h: 180 };
    const fixed = ensureContrast(start, "#fafafa", 7);
    expect(fixed.l).toBeLessThan(start.l);
    expect(contrastRatio(oklchToHex(fixed), "#fafafa")).toBeGreaterThanOrEqual(7);
  });

  it("leaves already-passing colors untouched", () => {
    const start = { l: 0.95, c: 0.005, h: 180 };
    expect(ensureContrast(start, "#101b1a", 4.5)).toEqual(start);
  });

  it("converges toward pure white when the target demands it", () => {
    const fixed = ensureContrast({ l: 0.5, c: 0.15, h: 30 }, "#000000", 20);
    expect(contrastRatio(oklchToHex(fixed), "#000000")).toBeGreaterThanOrEqual(20);
  });
});

describe("lightnessLadder", () => {
  const expectClose = (actual: number[], expected: number[]) => {
    expect(actual).toHaveLength(expected.length);
    actual.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 10));
  };

  it("steps evenly", () => {
    expectClose(lightnessLadder(0.2, 0.05, 3), [0.2, 0.25, 0.3]);
  });

  it("descends with negative steps and clamps at the extremes", () => {
    expectClose(lightnessLadder(0.05, -0.04, 3), [0.05, 0.01, 0]);
    expectClose(lightnessLadder(0.95, 0.04, 3), [0.95, 0.99, 1]);
  });
});

// ---------------------------------------------------------------------------
// Shipped generated presets — contrast guarantees
// ---------------------------------------------------------------------------

const OVERRIDE_KEYS: (keyof ThemeColorOverrides)[] = [
  "card", "cardForeground", "popover", "popoverForeground",
  "primary", "primaryForeground", "secondary", "secondaryForeground",
  "muted", "mutedForeground", "accent", "accentForeground",
  "destructive", "destructiveForeground", "success", "warning",
  "border", "input", "ring",
];

interface PresetCase {
  appearance: "dark" | "light";
  bodyMin: number;
  label: string;
  theme: DashboardTheme;
}

const PRESETS: PresetCase[] = [
  { label: "fabric-dark normal", theme: fabricDarkTheme, appearance: "dark", bodyMin: 4.5 },
  { label: "fabric-dark high", theme: fabricDarkHighContrastTheme, appearance: "dark", bodyMin: 7 },
  { label: "fabric-light normal", theme: fabricLightTheme, appearance: "light", bodyMin: 4.5 },
  { label: "fabric-light high", theme: fabricLightHighContrastTheme, appearance: "light", bodyMin: 7 },
];

describe.each(PRESETS)("$label", ({ theme, appearance, bodyMin }) => {
  const o = theme.colorOverrides!;
  const bg = theme.palette.background.hex;
  const body = theme.palette.midground.hex;

  it("defines every colorOverrides token as a hex color", () => {
    for (const key of OVERRIDE_KEYS) {
      expect(o[key], `colorOverrides.${key}`).toMatch(HEX);
    }
  });

  it(`body text on background meets >= ${bodyMin}:1`, () => {
    expect(contrastRatio(body, bg)).toBeGreaterThanOrEqual(bodyMin);
  });

  it("muted text on card meets WCAG AA (>= 4.5:1)", () => {
    expect(contrastRatio(o.mutedForeground!, o.card!)).toBeGreaterThanOrEqual(4.5);
  });

  it("surface foreground pairs all meet >= 4.5:1", () => {
    expect(contrastRatio(o.cardForeground!, o.card!)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(o.popoverForeground!, o.popover!)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(o.secondaryForeground!, o.secondary!)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(o.accentForeground!, o.accent!)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(o.primaryForeground!, o.primary!)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(o.destructiveForeground!, o.destructive!)).toBeGreaterThanOrEqual(4.5);
  });

  it("status tones read as text on the canvas at >= 4.5:1", () => {
    expect(contrastRatio(o.destructive!, bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(o.success!, bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(o.warning!, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it("accent clears the canvas at >= 3:1 (non-text)", () => {
    expect(contrastRatio(o.primary!, bg)).toBeGreaterThanOrEqual(3);
  });

  it("surfaces are monochrome (chroma clamped)", () => {
    for (const hex of [bg, o.card!, o.popover!, o.secondary!, o.muted!, o.accent!, o.border!]) {
      expect(hexToOklch(hex).c).toBeLessThanOrEqual(0.02);
    }
  });

  it("elevation steps lightness in the right direction", () => {
    const l = (hex: string) => hexToOklch(hex).l;
    if (appearance === "dark") {
      expect(l(o.card!)).toBeGreaterThan(l(bg));
      expect(l(o.popover!)).toBeGreaterThan(l(o.card!));
      expect(l(o.border!)).toBeGreaterThan(l(bg));
    } else {
      expect(l(o.card!)).toBeLessThan(l(bg));
      expect(l(o.popover!)).toBeLessThan(l(o.card!));
      expect(l(o.border!)).toBeLessThan(l(bg));
    }
  });

  it("classifies to its own appearance", () => {
    expect(themeAppearance(theme)).toBe(appearance);
  });

  it("keeps the DashboardTheme contract applyTheme relies on", () => {
    expect(theme.palette.foreground.alpha).toBe(0);
    expect(theme.palette.background.alpha).toBe(1);
    expect(theme.layout.radius).toBeTruthy();
    expect(theme.layout.density).toBeTruthy();
    expect(theme.typography.fontSans).toContain("system-ui");
    expect(theme.typography.fontMono).toContain("monospace");
    expect(theme.swatchColors).toHaveLength(3);
    expect(theme.terminalBackground).toMatch(HEX);
    expect(theme.terminalForeground).toMatch(HEX);
    expect(theme.seriesColors?.inputTokenAccent).toMatch(HEX);
    expect(theme.seriesColors?.outputTokenAccent).toMatch(HEX);
  });
});

describe("high-contrast variants", () => {
  it("share the preset name (surfaced via the contrast toggle, not new ids)", () => {
    expect(fabricDarkHighContrastTheme.name).toBe(fabricDarkTheme.name);
    expect(fabricLightHighContrastTheme.name).toBe(fabricLightTheme.name);
  });

  it("strictly increase body-text contrast over the normal variants", () => {
    const ratio = (t: DashboardTheme) =>
      contrastRatio(t.palette.midground.hex, t.palette.background.hex);
    expect(ratio(fabricDarkHighContrastTheme)).toBeGreaterThan(ratio(fabricDarkTheme));
    expect(ratio(fabricLightHighContrastTheme)).toBeGreaterThan(ratio(fabricLightTheme));
  });
});

// ---------------------------------------------------------------------------
// Generator robustness — hostile inputs still meet the guarantees
// ---------------------------------------------------------------------------

describe("generateTheme with awkward inputs", () => {
  it("fixes a low-contrast accent (yellow) on a light canvas", () => {
    const t = generateTheme({
      name: "x", label: "X", description: "",
      base: "#888888",
      accent: "#ffff00",
      appearance: "light",
    });
    const o = t.colorOverrides!;
    expect(contrastRatio(o.primary!, t.palette.background.hex)).toBeGreaterThanOrEqual(3);
    expect(contrastRatio(o.primaryForeground!, o.primary!)).toBeGreaterThanOrEqual(4.5);
  });

  it("meets AAA body text for a saturated base in dark high contrast", () => {
    const t = generateTheme({
      name: "x", label: "X", description: "",
      base: "#5e6ad2",
      accent: "#5e6ad2",
      appearance: "dark",
      contrast: "high",
    });
    expect(
      contrastRatio(t.palette.midground.hex, t.palette.background.hex),
    ).toBeGreaterThanOrEqual(7);
    // Saturated base still yields monochrome surfaces.
    expect(hexToOklch(t.palette.background.hex).c).toBeLessThanOrEqual(0.02);
    expect(hexToOklch(t.colorOverrides!.card!).c).toBeLessThanOrEqual(0.02);
  });

  it("respects density and radius passthrough", () => {
    const t = generateTheme({
      name: "x", label: "X", description: "",
      base: "#101b1a", accent: "#14b8a6", appearance: "dark",
      density: "compact", radius: "0",
    });
    expect(t.layout.density).toBe("compact");
    expect(t.layout.radius).toBe("0");
  });
});
