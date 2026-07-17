import { createContext, useContext } from "react";
import { BUILTIN_THEMES, defaultTheme } from "./presets";
import { FONT_CHOICES, THEME_DEFAULT_FONT_ID, type FontChoice } from "./fonts";
import type { ThemeContrast } from "./generate";
import type { DashboardTheme, ThemeListEntry } from "./types";
import {
  DEFAULT_TERMINAL_PREFS,
  type TerminalFontSize,
  type TerminalPrefs,
} from "@/lib/terminal-schemes";

// The context object, hook, and preference types live outside context.tsx so
// that file exports only components (Fast Refresh requirement) — a
// mixed-export provider file forces a full reload on every theme edit.

/** Appearance preference: pinned dark/light, or follow the OS. */
export type AppearancePref = "dark" | "light" | "system";
/** Contrast preference — applies to the generated theme pair. */
export type ContrastPref = ThemeContrast;

export type { TerminalFontSize, TerminalPrefs };
export { DEFAULT_TERMINAL_PREFS };

export interface ThemeContextValue {
  availableThemes: ThemeListEntry[];
  setTheme: (name: string) => void;
  theme: DashboardTheme;
  themeName: string;
  /** Active font-override id (`THEME_DEFAULT_FONT_ID` = no override). */
  fontId: string;
  /** Curated font catalog for the picker. */
  fontChoices: FontChoice[];
  /** Set the font override (independent of theme). */
  setFont: (id: string) => void;
  /** Appearance preference: pinned dark/light, or follow the OS. */
  appearance: AppearancePref;
  setAppearance: (pref: AppearancePref) => void;
  /** Contrast preference — applies to the generated theme pair. */
  contrast: ContrastPref;
  setContrast: (pref: ContrastPref) => void;
  /** Terminal appearance overrides (scheme / font / size). */
  terminalPrefs: TerminalPrefs;
  setTerminalScheme: (id: string) => void;
  setTerminalFont: (id: string) => void;
  setTerminalFontSize: (size: TerminalFontSize) => void;
}

export const ThemeContext = createContext<ThemeContextValue>({
  theme: defaultTheme,
  themeName: "fabric-light",
  availableThemes: Object.values(BUILTIN_THEMES).map((t) => ({
    name: t.name,
    label: t.label,
    description: t.description,
  })),
  setTheme: () => {},
  fontId: THEME_DEFAULT_FONT_ID,
  fontChoices: FONT_CHOICES,
  setFont: () => {},
  appearance: "light",
  setAppearance: () => {},
  contrast: "normal",
  setContrast: () => {},
  terminalPrefs: DEFAULT_TERMINAL_PREFS,
  setTerminalScheme: () => {},
  setTerminalFont: () => {},
  setTerminalFontSize: () => {},
});

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
