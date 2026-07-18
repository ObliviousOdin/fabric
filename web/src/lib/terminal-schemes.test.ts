import { describe, expect, it } from "vitest";
import { buildTerminalTheme } from "./terminal-theme";
import {
  DEFAULT_TERMINAL_FONT_FAMILY,
  getTerminalScheme,
  normalizeTerminalFontSize,
  resolveTerminalTheme,
  TERMINAL_FONT_CHOICES,
  TERMINAL_FONT_DEFAULT_ID,
  TERMINAL_SCHEMES,
  terminalFontFamily,
  terminalFontUrl,
  THEME_DEFAULT_SCHEME_ID,
} from "./terminal-schemes";

const HEX = /^#[0-9a-f]{6}$/;

describe("TERMINAL_SCHEMES", () => {
  it("has unique ids that never collide with the theme-default sentinel", () => {
    const ids = TERMINAL_SCHEMES.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).not.toContain(THEME_DEFAULT_SCHEME_ID);
  });

  it("every scheme carries a complete normalized-hex palette", () => {
    for (const scheme of TERMINAL_SCHEMES) {
      for (const [key, value] of Object.entries(scheme.theme)) {
        if (key === "selectionBackground") {
          expect(value, `${scheme.id}.${key}`).toMatch(/^#[0-9a-f]{6}44$/);
          continue;
        }
        expect(value, `${scheme.id}.${key}`).toMatch(HEX);
      }
      expect(scheme.theme.cursor).toBe(scheme.theme.foreground);
      expect(scheme.theme.cursorAccent).toBe(scheme.theme.background);
    }
  });
});

describe("resolveTerminalTheme", () => {
  it("returns the pinned scheme palette when a catalog id is set", () => {
    const dracula = resolveTerminalTheme("dracula", "#f8fafe", "#1d1f24");
    expect(dracula.background).toBe("#282a36");
    expect(dracula).toBe(getTerminalScheme("dracula")?.theme);
  });

  it("derives from the dashboard theme for the sentinel and unknown ids", () => {
    const derived = buildTerminalTheme("#f8fafe", "#1d1f24");
    expect(resolveTerminalTheme(THEME_DEFAULT_SCHEME_ID, "#f8fafe", "#1d1f24"))
      .toEqual(derived);
    expect(resolveTerminalTheme("no-such-scheme", "#f8fafe", "#1d1f24"))
      .toEqual(derived);
    expect(resolveTerminalTheme(undefined, "#f8fafe", "#1d1f24"))
      .toEqual(derived);
  });
});

describe("terminalFontFamily", () => {
  it("returns the default stack for the sentinel and unknown ids", () => {
    expect(terminalFontFamily(TERMINAL_FONT_DEFAULT_ID)).toBe(
      DEFAULT_TERMINAL_FONT_FAMILY,
    );
    expect(terminalFontFamily("papyrus")).toBe(DEFAULT_TERMINAL_FONT_FAMILY);
    expect(terminalFontFamily(undefined)).toBe(DEFAULT_TERMINAL_FONT_FAMILY);
  });

  it("prepends the chosen family ahead of the default stack", () => {
    const stack = terminalFontFamily("ibm-plex-mono");
    expect(stack.startsWith("'IBM Plex Mono', ")).toBe(true);
    expect(stack.endsWith(DEFAULT_TERMINAL_FONT_FAMILY)).toBe(true);
  });

  it("every catalog font resolves a vetted webfont URL", () => {
    for (const font of TERMINAL_FONT_CHOICES) {
      const url = terminalFontUrl(font.id);
      expect(url, font.id).toMatch(/^https:\/\/fonts\.googleapis\.com\//);
    }
    expect(terminalFontUrl(TERMINAL_FONT_DEFAULT_ID)).toBeUndefined();
  });
});

describe("normalizeTerminalFontSize", () => {
  it("passes through sane pixel sizes, including numeric strings", () => {
    expect(normalizeTerminalFontSize(14)).toBe(14);
    expect(normalizeTerminalFontSize("16")).toBe(16);
    expect(normalizeTerminalFontSize(13.6)).toBe(14);
  });

  it("coerces everything else to auto", () => {
    expect(normalizeTerminalFontSize("auto")).toBe("auto");
    expect(normalizeTerminalFontSize(4)).toBe("auto");
    expect(normalizeTerminalFontSize(400)).toBe("auto");
    expect(normalizeTerminalFontSize("huge")).toBe("auto");
    expect(normalizeTerminalFontSize(null)).toBe("auto");
    expect(normalizeTerminalFontSize(undefined)).toBe("auto");
    expect(normalizeTerminalFontSize(Number.NaN)).toBe("auto");
  });
});
