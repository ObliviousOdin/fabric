// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APPEARANCE_STORAGE_KEY,
  STORAGE_KEY,
  appearanceForThemeMigration,
  applyPersistedThemeEarly,
  canonicalizeThemeEntry,
  migrateThemeName,
} from "./apply";
import { BUILTIN_THEMES } from "./presets";

const HERITAGE_THEME_IDS = [
  "lens-5i",
  "nous-blue",
  "fabric-blue",
  "fabric-teal",
  "default-large",
] as const;

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-appearance");
  document.documentElement.removeAttribute("data-layout-variant");
  document.documentElement.removeAttribute("style");
  vi.restoreAllMocks();
});

describe("heritage theme migration", () => {
  it("uses Fabric Light by default for every retired identity", () => {
    for (const name of HERITAGE_THEME_IDS) {
      expect(migrateThemeName(name), name).toBe("fabric-light");
    }
  });

  it("uses Fabric Dark when dark appearance is explicit", () => {
    for (const name of HERITAGE_THEME_IDS) {
      expect(migrateThemeName(name, "dark"), name).toBe("fabric-dark");
    }
  });

  it("leaves current and user-defined theme ids unchanged", () => {
    expect(migrateThemeName("fabric-light", "dark")).toBe("fabric-light");
    expect(migrateThemeName("midnight", "dark")).toBe("midnight");
    expect(migrateThemeName("tenant-theme", "light")).toBe("tenant-theme");
  });

  it("only treats system as dark when the OS explicitly prefers dark", () => {
    expect(appearanceForThemeMigration(null, true)).toBe("light");
    expect(appearanceForThemeMigration("light", true)).toBe("light");
    expect(appearanceForThemeMigration("dark", false)).toBe("dark");
    expect(appearanceForThemeMigration("system", false)).toBe("light");
    expect(appearanceForThemeMigration("system", true)).toBe("dark");
  });
});

describe("primary theme catalog", () => {
  it("contains the canonical pair without heritage presets", () => {
    expect(Object.keys(BUILTIN_THEMES)).toEqual(
      expect.arrayContaining(["fabric-light", "fabric-dark"]),
    );
    for (const name of HERITAGE_THEME_IDS) {
      expect(BUILTIN_THEMES).not.toHaveProperty(name);
    }
  });

  it("canonicalizes heritage entries from older servers", () => {
    for (const name of HERITAGE_THEME_IDS) {
      expect(
        canonicalizeThemeEntry({
          name,
          label: `Retired ${name}`,
          description: "legacy",
        }),
      ).toEqual({
        name: "fabric-light",
        label: BUILTIN_THEMES["fabric-light"].label,
        description: BUILTIN_THEMES["fabric-light"].description,
      });
    }
  });
});

describe("pre-mount heritage migration", () => {
  function setColorScheme(dark: boolean) {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: dark,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    });
  }

  it("applies Fabric Light before React mounts when appearance is unset", () => {
    window.localStorage.setItem(STORAGE_KEY, "fabric-blue");

    applyPersistedThemeEarly();

    expect(document.documentElement.dataset.theme).toBe("fabric-light");
    expect(document.documentElement.dataset.appearance).toBe("light");
  });

  it("applies Fabric Dark before React mounts for explicit dark appearance", () => {
    window.localStorage.setItem(STORAGE_KEY, "fabric-teal");
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, "dark");

    applyPersistedThemeEarly();

    expect(document.documentElement.dataset.theme).toBe("fabric-dark");
    expect(document.documentElement.dataset.appearance).toBe("dark");
  });

  it("honors a dark OS preference in system mode", () => {
    setColorScheme(true);
    window.localStorage.setItem(STORAGE_KEY, "default-large");
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, "system");

    applyPersistedThemeEarly();

    expect(document.documentElement.dataset.theme).toBe("fabric-dark");
    expect(document.documentElement.dataset.appearance).toBe("dark");
  });
});
