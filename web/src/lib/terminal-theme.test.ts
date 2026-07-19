import { describe, expect, it } from "vitest";
import { contrastRatio } from "@/themes/generate";
import {
  AA_TERMINAL_SLOTS,
  buildTerminalTheme,
  DEFAULT_TERMINAL_BACKGROUND,
  DEFAULT_TERMINAL_FOREGROUND,
} from "./terminal-theme";

/** Backgrounds from the canonical generated light and dark theme pair. */
const BACKGROUNDS = [
  { name: "fabric-light", bg: "#f8fafe", fg: "#1d1f24" },
  { name: "fabric-dark", bg: "#06070b", fg: "#e4e8f0" },
] as const;

const HEX = /^#[0-9a-f]{6}$/;

describe("buildTerminalTheme", () => {
  for (const { name, bg, fg } of BACKGROUNDS) {
    it(`derives an AA-legible ANSI ramp on ${name}`, () => {
      const theme = buildTerminalTheme(bg, fg);
      expect(theme.background).toBe(bg);
      for (const slot of AA_TERMINAL_SLOTS) {
        const ratio = contrastRatio(theme[slot], bg);
        expect(
          ratio,
          `${slot} ${theme[slot]} is ${ratio.toFixed(2)}:1 on ${bg}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    });

    it(`keeps foreground/cursor legible on ${name}`, () => {
      const theme = buildTerminalTheme(bg, fg);
      expect(contrastRatio(theme.foreground, bg)).toBeGreaterThanOrEqual(4.5);
      expect(theme.cursor).toBe(theme.foreground);
      expect(theme.cursorAccent).toBe(bg);
    });
  }

  it("emits normalized hex for every color slot", () => {
    const theme = buildTerminalTheme("#F8FAFE", "#1D1F24");
    for (const [key, value] of Object.entries(theme)) {
      if (key === "selectionBackground") continue;
      expect(value, key).toMatch(HEX);
    }
    // Selection is the foreground at ~27% alpha — 8-digit hex.
    expect(theme.selectionBackground).toMatch(/^#[0-9a-f]{6}44$/);
  });

  it("repairs an illegible foreground/background pairing", () => {
    const theme = buildTerminalTheme("#f8fafe", "#ffffff");
    expect(contrastRatio(theme.foreground, "#f8fafe")).toBeGreaterThanOrEqual(
      4.5,
    );
  });

  it("falls back to the on-brand defaults for missing or garbage input", () => {
    const theme = buildTerminalTheme(undefined, "not-a-color");
    expect(theme.background).toBe(DEFAULT_TERMINAL_BACKGROUND);
    expect(theme.foreground).toBe(DEFAULT_TERMINAL_FOREGROUND);
    const short = buildTerminalTheme("#fff", undefined);
    expect(short.background).toBe("#ffffff");
  });

  it("maps SGR-37 white to a dark gray on light canvases (not literal white)", () => {
    const light = buildTerminalTheme("#f8fafe", "#1d1f24");
    expect(contrastRatio(light.white, "#f8fafe")).toBeGreaterThanOrEqual(4.5);
    const dark = buildTerminalTheme("#06070b", "#e4e8f0");
    expect(contrastRatio(dark.brightWhite, "#06070b")).toBeGreaterThanOrEqual(
      4.5,
    );
  });
});
