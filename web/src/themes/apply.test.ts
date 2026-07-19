// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APPEARANCE_STORAGE_KEY,
  STORAGE_KEY,
  applyPersistedThemeEarly,
} from "./apply";

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-appearance");
  document.documentElement.removeAttribute("data-layout-variant");
  document.documentElement.removeAttribute("style");
  vi.restoreAllMocks();
});

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

describe("pre-mount Fabric theme application", () => {
  it("applies Fabric Light when no preference is stored", () => {
    applyPersistedThemeEarly();

    expect(document.documentElement.dataset.theme).toBe("fabric-light");
    expect(document.documentElement.dataset.appearance).toBe("light");
  });

  it("applies the stored Fabric Dark theme", () => {
    window.localStorage.setItem(STORAGE_KEY, "fabric-dark");
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, "dark");

    applyPersistedThemeEarly();

    expect(document.documentElement.dataset.theme).toBe("fabric-dark");
    expect(document.documentElement.dataset.appearance).toBe("dark");
  });

  it("follows the OS preference in system mode", () => {
    setColorScheme(true);
    window.localStorage.setItem(STORAGE_KEY, "fabric-light");
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, "system");

    applyPersistedThemeEarly();

    expect(document.documentElement.dataset.theme).toBe("fabric-dark");
    expect(document.documentElement.dataset.appearance).toBe("dark");
  });
});
