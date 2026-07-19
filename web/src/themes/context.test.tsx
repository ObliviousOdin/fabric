// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getFontPref: vi.fn(),
    getTerminalPref: vi.fn(),
    getThemes: vi.fn(),
    setFontPref: vi.fn(),
    setTerminalPref: vi.fn(),
    setTheme: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));

import { ThemeProvider } from "./context";
import { STORAGE_KEY } from "./apply";
import { useTheme } from "./use-theme";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function ThemeProbe() {
  const { availableThemes, themeName } = useTheme();
  return (
    <output
      data-theme-name={themeName}
      data-theme-options={availableThemes.map((theme) => theme.name).join(",")}
    />
  );
}

describe("ThemeProvider Fabric contract", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    window.localStorage.clear();
    apiMock.getFontPref.mockReset().mockResolvedValue({ font: "theme" });
    apiMock.getThemes.mockReset().mockResolvedValue({
      active: "fabric-dark",
      themes: [
        {
          name: "fabric-light",
          label: "Fabric Light",
          description: "Canonical light",
        },
        {
          name: "fabric-dark",
          label: "Fabric Dark",
          description: "Canonical dark",
        },
        {
          name: "tenant-theme",
          label: "Tenant Theme",
          description: "Custom theme",
        },
      ],
    });
    apiMock.setFontPref.mockReset().mockResolvedValue({ ok: true });
    apiMock.getTerminalPref
      .mockReset()
      .mockResolvedValue({ scheme: "theme", font: "default", size: "auto" });
    apiMock.setTerminalPref.mockReset().mockResolvedValue({ ok: true });
    apiMock.setTheme.mockReset().mockResolvedValue({ ok: true });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-appearance");
    document.documentElement.removeAttribute("data-layout-variant");
    document.documentElement.removeAttribute("style");
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("adopts the server's Fabric-native active theme without rewriting it", async () => {
    window.localStorage.setItem(STORAGE_KEY, "fabric-light");

    await act(async () => {
      root.render(
        <ThemeProvider>
          <ThemeProbe />
        </ThemeProvider>,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    const probe = container.querySelector("output");
    expect(probe?.dataset.themeName).toBe("fabric-dark");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("fabric-dark");
    expect(probe?.dataset.themeOptions?.split(",")).toEqual(
      expect.arrayContaining(["fabric-light", "fabric-dark", "tenant-theme"]),
    );
    expect(apiMock.setTheme).not.toHaveBeenCalled();
  });
});
