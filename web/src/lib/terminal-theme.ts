/**
 * Shared theme-aware xterm.js palette builder.
 *
 * Both embedded terminals (ChatPage's TUI PTY and FabricConsoleModal's
 * console REPL) previously set only background/foreground, leaving
 * xterm's built-in dark-tuned ANSI defaults (or a hardcoded dark pastel
 * ramp) in place — on light themes ANSI output rendered near-invisible
 * ("white-washed"). This module derives the full 16-color ANSI ramp from
 * the active theme's terminal background/foreground, walking each slot's
 * lightness until it holds WCAG AA (>= 4.5:1) as text on that background.
 */

import {
  bestForeground,
  contrastRatio,
  ensureContrast,
  hexToOklch,
  isLightColor,
  oklchToHex,
} from "@/themes/generate";

/** Fallback pair for themes that don't declare terminal colors — matches
 *  the generated fabric-dark canvas/text so the fallback stays on-brand.
 *  (Previously #000000 / cream #f0e6d2, duplicated across three files.) */
export const DEFAULT_TERMINAL_BACKGROUND = "#0b0d12";
export const DEFAULT_TERMINAL_FOREGROUND = "#e4e8f0";

/** Shape consumed by xterm.js `ITheme`. */
export interface TerminalTheme {
  background: string;
  foreground: string;
  cursor: string;
  cursorAccent: string;
  selectionBackground: string;
  black: string;
  red: string;
  green: string;
  yellow: string;
  blue: string;
  magenta: string;
  cyan: string;
  white: string;
  brightBlack: string;
  brightRed: string;
  brightGreen: string;
  brightYellow: string;
  brightBlue: string;
  brightMagenta: string;
  brightCyan: string;
  brightWhite: string;
}

/** ANSI slots that must hold AA as text on the terminal background.
 *  `black` is exempt: it is overwhelmingly used as a background (SGR 40)
 *  or for text that is black *by definition*; forcing it to 4.5:1 on a
 *  dark canvas would make it light gray and break inverse-video UIs. */
export const AA_TERMINAL_SLOTS = [
  "red",
  "green",
  "yellow",
  "blue",
  "magenta",
  "cyan",
  "white",
  "brightBlack",
  "brightRed",
  "brightGreen",
  "brightYellow",
  "brightBlue",
  "brightMagenta",
  "brightCyan",
  "brightWhite",
] as const;

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/** Cursor + selection slots shared by this derived builder and the pinned
 *  catalog schemes (terminal-schemes.ts): block cursor in the foreground,
 *  cursor text in the background, selection = foreground at ~27% alpha —
 *  visible on any canvas without occluding the selected glyphs. */
export function cursorAndSelectionSlots(
  background: string,
  foreground: string,
): Pick<TerminalTheme, "cursor" | "cursorAccent" | "selectionBackground"> {
  return {
    cursor: foreground,
    cursorAccent: background,
    selectionBackground: `${foreground}44`,
  };
}

function normalizeHex(value: string | undefined, fallback: string): string {
  if (!value) return fallback;
  const v = value.trim();
  if (HEX_RE.test(v)) return v.toLowerCase();
  // Expand shorthand #rgb; anything else (rgb(), named colors) falls back
  // so downstream color math always receives a 6-digit hex.
  const short = /^#([0-9a-fA-F])([0-9a-fA-F])([0-9a-fA-F])$/.exec(v);
  if (short) {
    return `#${short[1]}${short[1]}${short[2]}${short[2]}${short[3]}${short[3]}`.toLowerCase();
  }
  return fallback;
}

/** Fixed hue/chroma seeds per chromatic slot; hues match the generator's
 *  status tones (red/green/yellow) plus the brand blue (H≈263) and the
 *  docs purple band (magenta). Lightness is re-derived per background. */
const CHROMATIC_SEEDS = {
  red: { h: 27, c: 0.19 },
  green: { h: 152, c: 0.13 },
  yellow: { h: 83, c: 0.14 },
  blue: { h: 262.7, c: 0.19 },
  magenta: { h: 295, c: 0.16 },
  cyan: { h: 195, c: 0.11 },
} as const;

function slot(
  seed: { h: number; c: number },
  l: number,
  bgHex: string,
): string {
  return oklchToHex(ensureContrast({ l, c: seed.c, h: seed.h }, bgHex, 4.5));
}

/** Neutral (black/white/gray) slots, AA-adjusted against the background
 *  where the slot is meant to carry text. */
function neutral(l: number, bgHex: string, minRatio: number): string {
  return oklchToHex(ensureContrast({ l, c: 0, h: 0 }, bgHex, minRatio));
}

/**
 * Build a complete xterm theme from the active dashboard theme's terminal
 * colors. Light/dark is decided by the background's luminance, so every
 * preset — generated pair, heritage teal, YAML themes — gets a legible
 * ramp without declaring one.
 */
export function buildTerminalTheme(
  background?: string,
  foreground?: string,
): TerminalTheme {
  const bg = normalizeHex(background, DEFAULT_TERMINAL_BACKGROUND);
  const light = isLightColor(bg);
  const fgFallback = light ? "#1d1f24" : DEFAULT_TERMINAL_FOREGROUND;
  let fg = normalizeHex(foreground, fgFallback);
  // A theme can pair a light background with a light foreground (or the
  // reverse) through YAML edits; repair rather than render invisible text.
  if (contrastRatio(fg, bg) < 4.5) {
    fg = oklchToHex(ensureContrast(hexToOklch(fg), bg, 4.5));
  }

  // Normal ramp sits near the generator's status lightness for the
  // appearance; the bright ramp moves away from the background.
  const normalL = light ? 0.52 : 0.72;
  const brightL = light ? 0.45 : 0.8;

  const theme: TerminalTheme = {
    background: bg,
    foreground: fg,
    ...cursorAndSelectionSlots(bg, fg),
    // `black` stays anchored to its semantic end of the ramp (see
    // AA_TERMINAL_SLOTS): true black on light canvases, a near-canvas
    // ink on dark ones so inverse-video blocks keep their shape.
    black: light ? "#000000" : neutral(0.22, bg, 1),
    red: slot(CHROMATIC_SEEDS.red, normalL, bg),
    green: slot(CHROMATIC_SEEDS.green, normalL, bg),
    yellow: slot(CHROMATIC_SEEDS.yellow, normalL, bg),
    blue: slot(CHROMATIC_SEEDS.blue, normalL, bg),
    magenta: slot(CHROMATIC_SEEDS.magenta, normalL, bg),
    cyan: slot(CHROMATIC_SEEDS.cyan, normalL, bg),
    // SGR 37 "white" carries default-ish body text in most TUIs, so on a
    // light canvas it must be a *dark* gray (ecosystem convention — e.g.
    // VS Code Light maps white to #555555), not literal white.
    white: light ? neutral(0.45, bg, 4.5) : neutral(0.85, bg, 4.5),
    // brightBlack ("gray") is the dim-text workhorse — the single most
    // common cause of washed-out TUI output when it defaults dark.
    brightBlack: neutral(light ? 0.5 : 0.65, bg, 4.5),
    brightRed: slot(CHROMATIC_SEEDS.red, brightL, bg),
    brightGreen: slot(CHROMATIC_SEEDS.green, brightL, bg),
    brightYellow: slot(CHROMATIC_SEEDS.yellow, brightL, bg),
    brightBlue: slot(CHROMATIC_SEEDS.blue, brightL, bg),
    brightMagenta: slot(CHROMATIC_SEEDS.magenta, brightL, bg),
    brightCyan: slot(CHROMATIC_SEEDS.cyan, brightL, bg),
    brightWhite: light ? neutral(0.35, bg, 4.5) : bestForeground(bg),
  };
  return theme;
}
