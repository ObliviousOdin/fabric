// @vitest-environment jsdom

import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { themeState } = vi.hoisted(() => ({
  themeState: { appearance: "light" as "dark" | "light" },
}));

vi.mock("@/components/AuthWidget", () => ({
  AuthWidget: () => <div data-sidebar-probe="auth" />,
}));
vi.mock("@/components/experience/ExperienceSwitcher", () => ({
  ExperienceSwitcher: () => <div data-sidebar-probe="experience" />,
}));
vi.mock("@/components/LanguageSwitcher", () => ({
  LanguageSwitcher: () => <div data-sidebar-probe="language" />,
}));
vi.mock("@/components/ProfileSwitcher", () => ({
  ProfileSwitcher: () => <div data-sidebar-probe="profile" />,
}));
vi.mock("@/components/SidebarStatusStrip", () => ({
  SidebarStatusStrip: () => <div data-sidebar-probe="status" />,
}));
vi.mock("@/components/SidebarFooter", () => ({
  SidebarFooter: () => <div data-sidebar-probe="footer" />,
}));
vi.mock("@/components/ThemeSwitcher", () => ({
  ThemeSwitcher: () => <div data-sidebar-probe="theme" />,
}));
vi.mock("@/i18n", () => ({
  useI18n: () => ({
    t: {
      app: {
        closeNavigation: "Close navigation",
        navigation: "Navigation",
        pluginNavSection: "Plugins",
      },
      common: { collapse: "Collapse", expand: "Expand" },
      language: { switchTo: "Switch language" },
      theme: { switchTheme: "Switch theme" },
    },
  }),
}));
vi.mock("@/plugins", () => ({
  PluginSlot: ({ name }: { name: string }) => <div data-plugin-slot={name} />,
}));
vi.mock("@/themes", () => ({
  themeAppearance: () => themeState.appearance,
  useTheme: () => ({ theme: { appearance: themeState.appearance } }),
}));
vi.mock("./SidebarIconWithTooltip", () => ({
  SidebarIconWithTooltip: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("./SidebarNavLink", () => ({
  SidebarNavLink: () => null,
}));
vi.mock("./SidebarSystemActions", () => ({
  SidebarSystemActions: () => <div data-sidebar-probe="system-actions" />,
}));

import { AppSidebar } from "./AppSidebar";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("AppSidebar brand header", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    themeState.appearance = "light";
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  async function render(
    collapsed: boolean,
    isDesktopCollapsed: boolean,
    surface: "admin" | "workspace" = "workspace",
  ) {
    await act(async () => {
      root.render(
        <AppSidebar
          closeMobile={() => {}}
          collapsed={collapsed}
          isDesktopCollapsed={isDesktopCollapsed}
          isMobile={false}
          mobileOpen={false}
          pluginItems={[]}
          sections={[]}
          status={null}
          surface={surface}
          toggleCollapsed={() => {}}
          tooltipWarmRef={{ current: 0 }}
        />,
      );
    });
  }

  it("follows the active theme on the workspace rail", async () => {
    await render(false, false, "workspace");

    expect(
      container.querySelector("[data-fabric-brand] img")?.getAttribute("src"),
    ).toBe("/brand/fabric-wordmark.svg");
    expect(
      container
        .querySelector("[data-fabric-brand]")
        ?.getAttribute("data-compact"),
    ).toBe("false");
    expect(
      container.querySelector('[data-plugin-slot="header-left"]'),
    ).not.toBeNull();
  });

  it("follows the active theme on the admin rail", async () => {
    await render(false, false, "admin");

    expect(
      container.querySelector("[data-fabric-brand] img")?.getAttribute("src"),
    ).toBe("/brand/fabric-wordmark.svg");

    themeState.appearance = "dark";
    await render(false, false, "admin");
    expect(
      container.querySelector("[data-fabric-brand] img")?.getAttribute("src"),
    ).toBe("/brand/fabric-wordmark-on-dark.svg");
  });

  it("keeps the mark and toggle in the desktop-collapsed header", async () => {
    await render(true, true);

    expect(
      container.querySelector("[data-fabric-brand] img")?.getAttribute("src"),
    ).toBe("/brand/fabric-mark.svg");
    expect(
      container
        .querySelector("[data-fabric-brand]")
        ?.getAttribute("data-compact"),
    ).toBe("true");
    expect(
      container.querySelector('button[aria-label="Expand"]'),
    ).not.toBeNull();

    const pluginSlot = container.querySelector(
      '[data-plugin-slot="header-left"]',
    );
    expect(pluginSlot).not.toBeNull();
    expect(pluginSlot?.parentElement?.className).toContain("lg:hidden");
  });

  it("treats the mobile rail as a focus-managed modal drawer", async () => {
    const opener = document.createElement("button");
    opener.textContent = "Open navigation";
    document.body.appendChild(opener);
    opener.focus();
    const closeMobile = vi.fn();

    const renderMobile = async (mobileOpen: boolean) => {
      await act(async () => {
        root.render(
          <AppSidebar
            closeMobile={closeMobile}
            collapsed={false}
            isDesktopCollapsed={false}
            isMobile
            mobileOpen={mobileOpen}
            pluginItems={[]}
            sections={[]}
            status={null}
            surface="workspace"
            toggleCollapsed={() => {}}
            tooltipWarmRef={{ current: 0 }}
          />,
        );
        await Promise.resolve();
      });
    };

    await renderMobile(true);
    const drawer = container.querySelector<HTMLElement>("#app-sidebar");
    expect(drawer?.getAttribute("role")).toBe("dialog");
    expect(drawer?.getAttribute("aria-modal")).toBe("true");
    expect(drawer?.contains(document.activeElement)).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");

    await act(async () => {
      document.activeElement?.dispatchEvent(
        new KeyboardEvent("keydown", {
          bubbles: true,
          cancelable: true,
          key: "Escape",
        }),
      );
    });
    expect(closeMobile).toHaveBeenCalledTimes(1);

    await renderMobile(false);
    expect(drawer?.getAttribute("aria-hidden")).toBe("true");
    expect(drawer?.hasAttribute("inert")).toBe(true);
    expect(document.activeElement).toBe(opener);
    expect(document.body.style.overflow).toBe("");
    opener.remove();
  });
});
