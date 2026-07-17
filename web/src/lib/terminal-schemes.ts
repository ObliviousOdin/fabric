/**
 * Curated terminal color-scheme + font catalog for the embedded terminals.
 *
 * The dashboard's default terminal palette is *derived* from the active
 * theme (see terminal-theme.ts) — legible everywhere, but not something a
 * user can point at and say "give me Dracula". This module layers an
 * explicit, user-selectable override on top, mirroring the font-override
 * architecture in `themes/fonts.ts`:
 *
 *   - `THEME_DEFAULT_SCHEME_ID` ("theme") = no override; keep deriving the
 *     ANSI ramp from the active dashboard theme.
 *   - Any catalog id = pin the terminal to that scheme's canonical 16-color
 *     ramp regardless of the dashboard theme.
 *
 * Same story for the terminal font: "default" keeps the built-in terminal
 * stack; a catalog id prepends that font (mono webfonts reused from the
 * main font catalog so their stylesheets are already vetted).
 *
 * Keep the id sets in sync with the backend allow-lists in
 * `fabric_cli/web_server.py` (`_TERMINAL_SCHEME_CHOICES` /
 * `_TERMINAL_FONT_CHOICES`) — the ids must match exactly.
 */

import {
  buildTerminalTheme,
  cursorAndSelectionSlots,
  type TerminalTheme,
} from "./terminal-theme";
import { getFontChoice } from "@/themes/fonts";

/** Sentinel id meaning "no override — derive from the active theme". */
export const THEME_DEFAULT_SCHEME_ID = "theme";

/** The terminal font stack both embedded terminals have always used.
 *  Exported so ChatPage / FabricConsoleModal stop duplicating the string. */
export const DEFAULT_TERMINAL_FONT_FAMILY =
  "'JetBrains Mono', 'Cascadia Mono', 'Fira Code', 'MesloLGS NF', 'Source Code Pro', Menlo, Consolas, 'DejaVu Sans Mono', monospace";

/** Sentinel id meaning "no terminal font override — use the default stack". */
export const TERMINAL_FONT_DEFAULT_ID = "default";

/** Terminal font-size override: `"auto"` keeps the responsive width-tier
 *  sizing in ChatPage (and the console modal's fixed default); a number
 *  pins the size in px. */
export type TerminalFontSize = number | "auto";

export const TERMINAL_FONT_SIZE_AUTO: TerminalFontSize = "auto";

/** Sizes offered by the picker. Persistence accepts any 8–32 int so a
 *  future free-form control doesn't need a migration. */
export const TERMINAL_FONT_SIZE_CHOICES: readonly TerminalFontSize[] = [
  "auto",
  12,
  14,
  16,
  18,
];

const MIN_TERMINAL_FONT_SIZE = 8;
const MAX_TERMINAL_FONT_SIZE = 32;

/** Coerce a persisted value (server/localStorage) to a valid size pref.
 *  ("auto" parses to NaN and falls through to the sentinel.) */
export function normalizeTerminalFontSize(
  value: unknown,
): TerminalFontSize {
  const n = Math.round(
    typeof value === "string" ? Number.parseInt(value, 10) : Number(value),
  );
  if (
    Number.isFinite(n) &&
    n >= MIN_TERMINAL_FONT_SIZE &&
    n <= MAX_TERMINAL_FONT_SIZE
  ) {
    return n;
  }
  return "auto";
}

export interface TerminalFontChoice {
  /** Stable id persisted in config / localStorage. Matches the main font
   *  catalog id when the font comes from there (so its vetted webfont URL
   *  is reused). */
  id: string;
  /** Human-readable label shown in the picker. */
  label: string;
  /** Quoted CSS family prepended to `DEFAULT_TERMINAL_FONT_FAMILY`. */
  family: string;
}

/** Mono fonts offered for the terminal. All reuse main-catalog ids, so
 *  `getFontChoice(id).fontUrl` yields the (already vetted) stylesheet to
 *  inject when the override is active. */
export const TERMINAL_FONT_CHOICES: readonly TerminalFontChoice[] = [
  { id: "jetbrains-mono", label: "JetBrains Mono", family: "'JetBrains Mono'" },
  { id: "ibm-plex-mono", label: "IBM Plex Mono", family: "'IBM Plex Mono'" },
  { id: "space-mono", label: "Space Mono", family: "'Space Mono'" },
];

const TERMINAL_FONT_BY_ID: Record<string, TerminalFontChoice> =
  Object.fromEntries(TERMINAL_FONT_CHOICES.map((f) => [f.id, f]));

export function getTerminalFontChoice(
  id: string | null | undefined,
): TerminalFontChoice | undefined {
  if (!id || id === TERMINAL_FONT_DEFAULT_ID) return undefined;
  return TERMINAL_FONT_BY_ID[id];
}

/** Resolve a terminal font pref to the CSS stack xterm should use. */
export function terminalFontFamily(fontId: string | null | undefined): string {
  const choice = getTerminalFontChoice(fontId);
  if (!choice) return DEFAULT_TERMINAL_FONT_FAMILY;
  return `${choice.family}, ${DEFAULT_TERMINAL_FONT_FAMILY}`;
}

/** Webfont stylesheet URL for a terminal font override (undefined for the
 *  default stack and for system fonts). */
export function terminalFontUrl(
  fontId: string | null | undefined,
): string | undefined {
  const choice = getTerminalFontChoice(fontId);
  if (!choice) return undefined;
  return getFontChoice(choice.id)?.fontUrl;
}

export interface TerminalSchemeChoice {
  /** Stable id persisted in config / localStorage. */
  id: string;
  /** Human-readable label shown in the picker. */
  label: string;
  /** Full xterm palette. */
  theme: TerminalTheme;
}

/** Fill the cursor/selection slots via the shared helper the derived
 *  builder uses, so catalog entries only have to state bg/fg + the 16
 *  ANSI colors. */
function defineScheme(
  id: string,
  label: string,
  colors: Omit<
    TerminalTheme,
    "cursor" | "cursorAccent" | "selectionBackground"
  >,
): TerminalSchemeChoice {
  return {
    id,
    label,
    theme: {
      ...colors,
      ...cursorAndSelectionSlots(colors.background, colors.foreground),
    },
  };
}

/**
 * The curated set — canonical palettes for widely-loved terminal schemes.
 * Order is the display order in the picker.
 *
 * Palettes are used VERBATIM — deliberately not run through the WCAG-AA
 * lightness walk that `buildTerminalTheme` applies to derived palettes.
 * Users picking Dracula/Solarized/etc. expect the canonical colors (dim
 * slots and all, e.g. Solarized's muted brights), exactly as VS Code and
 * iTerm ship them; "Theme default" remains the AA-guaranteed option.
 */
export const TERMINAL_SCHEMES: readonly TerminalSchemeChoice[] = [
  defineScheme("dracula", "Dracula", {
    background: "#282a36",
    foreground: "#f8f8f2",
    black: "#21222c",
    red: "#ff5555",
    green: "#50fa7b",
    yellow: "#f1fa8c",
    blue: "#bd93f9",
    magenta: "#ff79c6",
    cyan: "#8be9fd",
    white: "#f8f8f2",
    brightBlack: "#6272a4",
    brightRed: "#ff6e6e",
    brightGreen: "#69ff94",
    brightYellow: "#ffffa5",
    brightBlue: "#d6acff",
    brightMagenta: "#ff92df",
    brightCyan: "#a4ffff",
    brightWhite: "#ffffff",
  }),
  defineScheme("one-dark", "One Dark", {
    background: "#282c34",
    foreground: "#abb2bf",
    black: "#282c34",
    red: "#e06c75",
    green: "#98c379",
    yellow: "#e5c07b",
    blue: "#61afef",
    magenta: "#c678dd",
    cyan: "#56b6c2",
    white: "#abb2bf",
    brightBlack: "#5c6370",
    brightRed: "#e06c75",
    brightGreen: "#98c379",
    brightYellow: "#e5c07b",
    brightBlue: "#61afef",
    brightMagenta: "#c678dd",
    brightCyan: "#56b6c2",
    brightWhite: "#c8ccd4",
  }),
  defineScheme("nord", "Nord", {
    background: "#2e3440",
    foreground: "#d8dee9",
    black: "#3b4252",
    red: "#bf616a",
    green: "#a3be8c",
    yellow: "#ebcb8b",
    blue: "#81a1c1",
    magenta: "#b48ead",
    cyan: "#88c0d0",
    white: "#e5e9f0",
    brightBlack: "#4c566a",
    brightRed: "#bf616a",
    brightGreen: "#a3be8c",
    brightYellow: "#ebcb8b",
    brightBlue: "#81a1c1",
    brightMagenta: "#b48ead",
    brightCyan: "#8fbcbb",
    brightWhite: "#eceff4",
  }),
  defineScheme("gruvbox-dark", "Gruvbox Dark", {
    background: "#282828",
    foreground: "#ebdbb2",
    black: "#282828",
    red: "#cc241d",
    green: "#98971a",
    yellow: "#d79921",
    blue: "#458588",
    magenta: "#b16286",
    cyan: "#689d6a",
    white: "#a89984",
    brightBlack: "#928374",
    brightRed: "#fb4934",
    brightGreen: "#b8bb26",
    brightYellow: "#fabd2f",
    brightBlue: "#83a598",
    brightMagenta: "#d3869b",
    brightCyan: "#8ec07c",
    brightWhite: "#ebdbb2",
  }),
  defineScheme("monokai", "Monokai", {
    background: "#272822",
    foreground: "#f8f8f2",
    black: "#272822",
    red: "#f92672",
    green: "#a6e22e",
    yellow: "#f4bf75",
    blue: "#66d9ef",
    magenta: "#ae81ff",
    cyan: "#a1efe4",
    white: "#f8f8f2",
    brightBlack: "#75715e",
    brightRed: "#f92672",
    brightGreen: "#a6e22e",
    brightYellow: "#f4bf75",
    brightBlue: "#66d9ef",
    brightMagenta: "#ae81ff",
    brightCyan: "#a1efe4",
    brightWhite: "#f9f8f5",
  }),
  defineScheme("solarized-dark", "Solarized Dark", {
    background: "#002b36",
    foreground: "#839496",
    black: "#073642",
    red: "#dc322f",
    green: "#859900",
    yellow: "#b58900",
    blue: "#268bd2",
    magenta: "#d33682",
    cyan: "#2aa198",
    white: "#eee8d5",
    brightBlack: "#586e75",
    brightRed: "#cb4b16",
    brightGreen: "#586e75",
    brightYellow: "#657b83",
    brightBlue: "#839496",
    brightMagenta: "#6c71c4",
    brightCyan: "#93a1a1",
    brightWhite: "#fdf6e3",
  }),
  defineScheme("solarized-light", "Solarized Light", {
    background: "#fdf6e3",
    foreground: "#657b83",
    black: "#073642",
    red: "#dc322f",
    green: "#859900",
    yellow: "#b58900",
    blue: "#268bd2",
    magenta: "#d33682",
    cyan: "#2aa198",
    white: "#eee8d5",
    brightBlack: "#002b36",
    brightRed: "#cb4b16",
    brightGreen: "#586e75",
    brightYellow: "#657b83",
    brightBlue: "#839496",
    brightMagenta: "#6c71c4",
    brightCyan: "#93a1a1",
    brightWhite: "#fdf6e3",
  }),
];

const SCHEME_BY_ID: Record<string, TerminalSchemeChoice> = Object.fromEntries(
  TERMINAL_SCHEMES.map((s) => [s.id, s]),
);

/** Look up a scheme by id. Returns undefined for the theme-default
 *  sentinel and for any unknown id. */
export function getTerminalScheme(
  id: string | null | undefined,
): TerminalSchemeChoice | undefined {
  if (!id || id === THEME_DEFAULT_SCHEME_ID) return undefined;
  return SCHEME_BY_ID[id];
}

/**
 * Resolve the effective xterm theme: a catalog scheme when one is pinned,
 * otherwise the palette derived from the active dashboard theme's terminal
 * colors (existing behavior).
 */
export function resolveTerminalTheme(
  schemeId: string | null | undefined,
  themeBackground?: string,
  themeForeground?: string,
): TerminalTheme {
  const scheme = getTerminalScheme(schemeId);
  if (scheme) return scheme.theme;
  return buildTerminalTheme(themeBackground, themeForeground);
}

/** User preferences for the embedded xterm terminals (Chat TUI + Fabric
 *  Console). Each field layers an override on the theme-derived default:
 *  `scheme` pins a catalog ANSI palette (`"theme"` = derive from theme),
 *  `font` prepends a catalog mono font (`"default"` = built-in stack),
 *  `size` pins the px font size (`"auto"` = responsive default). */
export interface TerminalPrefs {
  scheme: string;
  font: string;
  size: TerminalFontSize;
}

export const DEFAULT_TERMINAL_PREFS: TerminalPrefs = {
  scheme: THEME_DEFAULT_SCHEME_ID,
  font: TERMINAL_FONT_DEFAULT_ID,
  size: TERMINAL_FONT_SIZE_AUTO,
};

/** Coerce untrusted prefs (localStorage JSON / server response) to a valid
 *  `TerminalPrefs` — unknown ids fall back to their sentinels rather than
 *  wedging the pickers. */
export function normalizeTerminalPrefs(raw: unknown): TerminalPrefs {
  const obj =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const scheme =
    typeof obj.scheme === "string" && getTerminalScheme(obj.scheme)
      ? obj.scheme
      : THEME_DEFAULT_SCHEME_ID;
  const font =
    typeof obj.font === "string" && getTerminalFontChoice(obj.font)
      ? obj.font
      : TERMINAL_FONT_DEFAULT_ID;
  return { scheme, font, size: normalizeTerminalFontSize(obj.size) };
}
