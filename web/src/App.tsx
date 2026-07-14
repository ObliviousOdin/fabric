import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Menu } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { SelectionSwitcher } from "@nous-research/ui/ui/components/selection-switcher";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { cn } from "@/lib/utils";
import { useBelowBreakpoint } from "@nous-research/ui/hooks/use-below-breakpoint";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import { PageHeaderProvider } from "@/contexts/PageHeaderProvider";
import { ProfileProvider } from "@/contexts/ProfileProvider";
import { useProfileScope } from "@/contexts/useProfileScope";
import { ProfileScopeBanner } from "@/components/ProfileScopeBanner";
import {
  shouldRenderPersistentChat,
  usePersistentActiveMount,
} from "@/components/chat/persistent-chat-host";
import { AppSidebar } from "@/components/sidebar/AppSidebar";
import {
  BUILTIN_NAV_ITEMS,
  buildSidebarSections,
} from "@/components/sidebar/nav-model";
import type { NavItem, NavSection } from "@/components/sidebar/nav-model";
import { CommandPalette } from "@/components/CommandPalette";
import { ShortcutHelp } from "@/components/ShortcutHelp";
import { matchesCombo, useShortcut } from "@/hooks/useShortcutRegistry";
import { useI18n } from "@/i18n";
import { PluginPage, PluginSlot, usePlugins } from "@/plugins";
import { PluginAliasRedirect } from "@/plugins/PluginAliasRedirect";
import type { PluginManifest } from "@/plugins";
import { useTheme } from "@/themes";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";
import { api } from "@/lib/api";
import {
  APP_ROUTES,
  DEFAULT_ROUTE,
  canonicalPathForPath,
  canonicalPluginTargetPath,
  isBuiltinPath,
  isChatPath,
  overrideForPath,
  overrideForRoute,
  pluginRouteMetadata,
  routeForPath,
  routeLayoutForPath,
  routeSurfaceForPath,
} from "@/app/routes";

const ChatPage = lazy(() => import("@/pages/ChatPage"));
const CHAT_ROUTE = APP_ROUTES.find((route) => route.id === "chat")!;

function PreservingRedirect({ to }: { to: string }) {
  const { hash, search } = useLocation();
  return <Navigate replace to={{ pathname: to, search, hash }} />;
}

function RootRedirect() {
  return <PreservingRedirect to={DEFAULT_ROUTE} />;
}

function UnknownRouteFallback({ pluginsLoading }: { pluginsLoading: boolean }) {
  if (pluginsLoading) {
    // Render nothing during the plugin-load window — a spinner here would just flash.
    return null;
  }
  // Unknown URLs may contain sensitive query/hash material. Do not carry it
  // onto Home; preservation is reserved for cataloged legacy aliases.
  return <Navigate replace to={DEFAULT_ROUTE} />;
}

/**
 * Chat is hosted persistently outside `<Routes>` after its first visit so its
 * PTY, WebSocket and xterm instance survive navigation. This sink claims both
 * the canonical route and its legacy alias without creating a second chat UI.
 */
function ChatRouteSink() {
  return null;
}

function RouteLoading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className="flex min-h-40 min-w-0 flex-1 items-center justify-center"
    >
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner />
        <span>Loading…</span>
      </div>
    </div>
  );
}

function buildRoutes(
  manifests: readonly PluginManifest[],
  embeddedChat: boolean,
): Array<{
  key: string;
  path: string;
  element: ReactNode;
}> {
  const routes: Array<{
    key: string;
    path: string;
    element: ReactNode;
  }> = [];

  const rootOverride = overrideForPath("/", manifests);
  routes.push({
    key: rootOverride ? `override:${rootOverride.name}:root` : "root",
    path: "/",
    element: rootOverride ? (
      <PluginPage name={rootOverride.name} />
    ) : (
      <RootRedirect />
    ),
  });

  for (const route of APP_ROUTES) {
    const override = overrideForRoute(route, manifests);
    let element: ReactNode;
    if (override) {
      element = <PluginPage name={override.name} />;
    } else if (route.persistent) {
      element = embeddedChat ? <ChatRouteSink /> : <RootRedirect />;
    } else if (route.component) {
      const Component = route.component;
      element = (
        <Suspense fallback={<RouteLoading />}>
          <Component />
        </Suspense>
      );
    } else {
      element = <RootRedirect />;
    }

    routes.push({
      key: `builtin:${route.id}`,
      path: route.path,
      element,
    });

    for (const alias of route.aliases ?? []) {
      routes.push({
        key: `alias:${route.id}:${alias}`,
        path: alias,
        element: <PreservingRedirect to={route.path} />,
      });
    }
  }

  for (const m of manifests) {
    if (m.tab.override) continue;
    if (m.tab.hidden) continue;
    if (m.tab.path === "/" || isBuiltinPath(m.tab.path)) continue;
    routes.push({
      key: `plugin:${m.name}`,
      path: m.tab.path,
      element: <PluginPage name={m.name} />,
    });
  }

  for (const m of manifests) {
    if (!m.tab.hidden) continue;
    if (m.tab.path === "/" || isBuiltinPath(m.tab.path) || m.tab.override) {
      continue;
    }
    routes.push({
      key: `plugin:hidden:${m.name}`,
      path: m.tab.path,
      element: <PluginPage name={m.name} />,
    });
  }

  // Aliases are compatibility-only routes. Canonical plugin paths, built-in
  // pages, and earlier aliases always win so a plugin cannot shadow another
  // product surface by declaring an alias for it.
  const claimedPaths = new Set([
    "/",
    ...APP_ROUTES.flatMap((route) => [route.path, ...(route.aliases ?? [])]),
  ]);
  for (const m of manifests) {
    claimedPaths.add(
      canonicalPluginTargetPath(m.tab.override ?? m.tab.path),
    );
  }
  for (const m of manifests) {
    const canonicalPath = canonicalPluginTargetPath(
      m.tab.override ?? m.tab.path,
    );
    for (const alias of m.tab.aliases ?? []) {
      if (!alias.startsWith("/") || claimedPaths.has(alias)) continue;
      claimedPaths.add(alias);
      routes.push({
        key: `plugin-alias:${m.name}:${alias}`,
        path: alias,
        element: <PluginAliasRedirect to={canonicalPath} />,
      });
    }
  }

  return routes;
}

const SIDEBAR_COLLAPSED_KEY = "fabric-sidebar-collapsed";
const LEGACY_SIDEBAR_COLLAPSED_KEY = "hermes-sidebar-collapsed";

export default function App() {
  return (
    <ProfileProvider>
      <AppShell />
    </ProfileProvider>
  );
}

function AppShell() {
  const { t } = useI18n();
  const { profile } = useProfileScope();
  const { pathname } = useLocation();
  const { manifests, loading: pluginsLoading } = usePlugins();
  const { theme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  const [collapsed, setCollapsed] = useState(() => {
    try {
      const saved =
        localStorage.getItem(SIDEBAR_COLLAPSED_KEY) ??
        localStorage.getItem(LEGACY_SIDEBAR_COLLAPSED_KEY);
      if (saved !== null) {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, saved);
        localStorage.removeItem(LEGACY_SIDEBAR_COLLAPSED_KEY);
      }
      return saved === "true";
    } catch {
      return false;
    }
  });
  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
        localStorage.removeItem(LEGACY_SIDEBAR_COLLAPSED_KEY);
      } catch { /* localStorage may be unavailable in private browsing */ }
      return next;
    });
  }, []);
  const isMobile = useBelowBreakpoint(1024);
  const isDesktopCollapsed = collapsed && !isMobile;
  const tooltipWarmRef = useRef(0);
  const sidebarStatus = useSidebarStatus(profile);
  const normalizedPath = pathname.replace(/\/$/, "") || "/";
  const activeRoute = routeForPath(pathname);
  const currentCanonicalPath =
    canonicalPathForPath(pathname) ?? normalizedPath;
  const isDocsRoute = activeRoute?.id === "help";
  const isChatRoute = isChatPath(pathname);
  const embeddedChat = isDashboardEmbeddedChatEnabled();
  const {
    hasMountedActiveChat: chatMountedActive,
    markActiveChatMounted,
  } = usePersistentActiveMount();

  // `dashboard.show_token_analytics` gates the Analytics nav item.  The
  // page itself remains reachable by URL (it renders an explanation when
  // the flag is off — see AnalyticsPage), but hiding the nav entry avoids
  // surfacing misleading token/cost numbers in the sidebar.  Default off.
  const [showTokenAnalytics, setShowTokenAnalytics] = useState(false);
  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        const dash = (cfg?.dashboard ?? {}) as {
          show_token_analytics?: unknown;
        };
        setShowTokenAnalytics(dash.show_token_analytics === true);
      })
      .catch(() => setShowTokenAnalytics(false));
  }, []);

  // A plugin can replace the built-in /chat page via `tab.override: "/chat"`
  // in its manifest.  When one does, `buildRoutes` already swaps the route
  // element for <PluginPage /> — but we also have to suppress the
  // persistent ChatPage host below, or the plugin's page and the built-in
  // terminal would paint on top of each other.  The override is niche
  // (nothing ships overriding /chat today) but it's an advertised
  // extension point, so preserve the pre-persistence contract: when a
  // plugin owns /chat, the built-in chat UI is entirely absent.
  //
  // Waiting on `pluginsLoading` is load-bearing: manifests arrive
  // asynchronously from /api/dashboard/plugins, so on initial render
  // `chatOverriddenByPlugin` is always false.  Without the loading
  // gate, the persistent host would mount, spawn a PTY, and THEN get
  // yanked out from under the user when the plugin's manifest resolves
  // — killing the session mid-paint.  Delaying host mount by the
  // plugin-load window (typically <50ms, worst case 2s safety timeout)
  // is the cheaper trade-off.
  const chatOverriddenByPlugin = useMemo(
    () => overrideForRoute(CHAT_ROUTE, manifests) !== undefined,
    [manifests],
  );

  const builtinNav = useMemo(
    () =>
      BUILTIN_NAV_ITEMS.filter(
        (item) =>
          (embeddedChat || item.path !== CHAT_ROUTE.path) &&
          (showTokenAnalytics || item.path !== "/workspace/insights"),
      ),
    [embeddedChat, showTokenAnalytics],
  );

  const sidebarNavBySurface = useMemo(
    () => ({
      workspace: buildSidebarSections(builtinNav, manifests, "workspace"),
      admin: buildSidebarSections(builtinNav, manifests, "admin"),
    }),
    [builtinNav, manifests],
  );
  const navPathsForSurface = (surface: "workspace" | "admin") => {
    const nav = sidebarNavBySurface[surface];
    return [...nav.sections.flatMap((section) => section.items), ...nav.pluginItems]
      .map((item) => item.path.replace(/\/$/, "") || "/")
      .includes(normalizedPath);
  };
  const directPlugin = manifests.find(
    (manifest) =>
      (manifest.tab.path.replace(/\/$/, "") || "/") === normalizedPath,
  );
  const activeSurface = activeRoute
    ? routeSurfaceForPath(pathname)
    : navPathsForSurface("admin")
      ? "admin"
      : navPathsForSurface("workspace")
        ? "workspace"
        : directPlugin
          ? directPlugin.tab.layout === "workspace"
            ? "workspace"
            : "admin"
          : routeSurfaceForPath(pathname);
  const sidebarNav = sidebarNavBySurface[activeSurface];
  const commandNav = useMemo(
    () => ({
      sections: [
        ...sidebarNavBySurface.workspace.sections,
        ...sidebarNavBySurface.admin.sections,
      ],
      pluginItems: [
        ...sidebarNavBySurface.workspace.pluginItems,
        ...sidebarNavBySurface.admin.pluginItems,
      ],
    }),
    [sidebarNavBySurface],
  );
  const routes = useMemo(
    () => buildRoutes(manifests, embeddedChat),
    [embeddedChat, manifests],
  );
  // Hidden plugin routes still need their layout metadata when opened by URL;
  // visibility only controls navigation discovery, not workspace chrome.
  const pluginTabMeta = useMemo(
    () => pluginRouteMetadata(manifests),
    [manifests],
  );

  const layoutVariant = theme.layoutVariant ?? "standard";
  const isWorkspaceRoute = useMemo(
    () => {
      if (routeLayoutForPath(pathname) === "workspace") return true;
      return pluginTabMeta.some(
        (tab) =>
          tab.layout === "workspace" &&
          (tab.path.replace(/\/+$/, "") || "/") === currentCanonicalPath,
      );
    },
    [currentCanonicalPath, pathname, pluginTabMeta],
  );

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1024px)");
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) setMobileOpen(false);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return (
    <div
      data-layout-variant={layoutVariant}
      className="flex h-dvh max-h-dvh min-h-0 flex-col overflow-hidden bg-background-base text-text-primary antialiased"
    >
      <SelectionSwitcher />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0"
      >
        <PluginSlot name="backdrop" />
      </div>

      <header
        aria-hidden={mobileOpen ? true : undefined}
        inert={mobileOpen ? true : undefined}
        className={cn(
          "lg:hidden fixed top-0 left-0 right-0 z-40 min-h-14",
          "flex items-center gap-2 px-4 py-2",
          "border-b border-current/20",
          "bg-background-base",
        )}
        style={{
          // No built-in theme populates the header component bucket, so the
          // var needs an explicit canvas fallback — an empty background here
          // rendered the mobile header transparent over scrolled content.
          background:
            "var(--component-header-background, var(--background-base))",
          borderImage: "var(--component-header-border-image)",
          clipPath: "var(--component-header-clip-path)",
        }}
      >
        <Button
          ghost
          size="icon"
          onClick={() => setMobileOpen(true)}
          aria-label={t.app.openNavigation}
          aria-expanded={mobileOpen}
          aria-controls="app-sidebar"
          className="text-text-secondary hover:text-midground"
        >
          <Menu />
        </Button>

        <Typography className="font-sans text-[1rem] font-semibold leading-none tracking-[-0.01em] text-midground">
          {t.app.brand}
        </Typography>
      </header>

      {mobileOpen && (
        <Button
          ghost
          aria-hidden="true"
          tabIndex={-1}
          onClick={closeMobile}
          className={cn(
            "lg:hidden fixed inset-0 z-40 p-0 block",
            "bg-black/70",
          )}
        />
      )}

      <PluginSlot name="header-banner" />
      <ProfileScopeBanner />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden pt-14 lg:pt-0">
        <div className="flex min-h-0 min-w-0 flex-1">
          <AppSidebar
            closeMobile={closeMobile}
            collapsed={collapsed}
            isDesktopCollapsed={isDesktopCollapsed}
            isMobile={isMobile}
            mobileOpen={mobileOpen}
            surface={activeSurface}
            pluginItems={sidebarNav.pluginItems}
            sections={sidebarNav.sections}
            status={sidebarStatus}
            toggleCollapsed={toggleCollapsed}
            tooltipWarmRef={tooltipWarmRef}
          />

          <PageHeaderProvider pluginTabs={pluginTabMeta}>
            <div
              className={cn(
                "relative z-2 flex min-w-0 min-h-0 flex-1 flex-col",
                isWorkspaceRoute ? "px-0" : "px-3 sm:px-6",
                isWorkspaceRoute
                  ? "pb-0 pt-0"
                  : isChatRoute
                    ? "pb-0 pt-1 sm:pt-2 lg:pt-4"
                    : "pt-2 sm:pt-4 lg:pt-6",
                isDocsRoute && "min-h-0 flex-1",
              )}
            >
              <PluginSlot name="pre-main" />
              <div
                className={cn(
                  "w-full min-w-0",
                  !isChatRoute && !isWorkspaceRoute &&
                    "pb-[calc(2rem+env(safe-area-inset-bottom,0px))] lg:pb-8",
                  (isDocsRoute || isChatRoute || isWorkspaceRoute) &&
                    "min-h-0 flex flex-1 flex-col",
                )}
              >
                <ProfileKeyedRoutes>
                  <Routes>
                    {routes.map(({ key, path, element }) => (
                      <Route key={key} path={path} element={element} />
                    ))}
                    <Route
                      path="*"
                      element={
                        <UnknownRouteFallback pluginsLoading={pluginsLoading} />
                      }
                    />
                  </Routes>
                </ProfileKeyedRoutes>

                {embeddedChat &&
                  !chatOverriddenByPlugin &&
                  (chatMountedActive || isChatRoute) &&
                  (pluginsLoading ? (
                    isChatRoute ? (
                      <div
                        className="flex min-h-0 min-w-0 flex-1 items-center justify-center"
                        aria-busy="true"
                        aria-live="polite"
                      >
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Spinner />
                          <span>Loading chat…</span>
                        </div>
                      </div>
                    ) : null
                  ) : shouldRenderPersistentChat(
                      isChatRoute,
                      chatMountedActive,
                      pluginsLoading,
                    ) ? (
                    <div
                      data-chat-active={isChatRoute ? "true" : "false"}
                      className={cn(
                        "min-h-0 min-w-0",
                        isChatRoute ? "flex flex-1 flex-col" : "hidden",
                      )}
                      aria-hidden={!isChatRoute}
                    >
                      <Suspense fallback={<RouteLoading />}>
                        <ChatPage
                          isActive={isChatRoute}
                          onActiveMount={markActiveChatMounted}
                        />
                      </Suspense>
                    </div>
                  ) : null)}
              </div>
              <PluginSlot name="post-main" />
            </div>
          </PageHeaderProvider>
        </div>
      </div>

      <AppCommandLayer
        embeddedChat={embeddedChat}
        pluginItems={commandNav.pluginItems}
        sections={commandNav.sections}
        toggleCollapsed={toggleCollapsed}
      />

      <PluginSlot name="overlay" />
    </div>
  );
}

/**
 * Global command palette (⌘K) + shortcut registry wiring. Lives inside the
 * app shell so it can reuse the exact nav structures the sidebar renders
 * (Pages in the palette can never drift from the sidebar) and the shared
 * sidebar-collapse toggle. The global shortcuts are registered here;
 * ShortcutHelp lists whatever the registry currently holds.
 */
function AppCommandLayer({
  embeddedChat,
  pluginItems,
  sections,
  toggleCollapsed,
}: {
  embeddedChat: boolean;
  pluginItems: NavItem[];
  sections: NavSection[];
  toggleCollapsed: () => void;
}) {
  const { t } = useI18n();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const scope = t.commandPalette?.scopeGlobal ?? "Global";

  useShortcut({
    combo: "mod+k",
    description: t.commandPalette?.openPalette ?? "Open command palette",
    handler: () => {
      setHelpOpen(false);
      setPaletteOpen((o) => !o);
    },
    scope,
  });
  useShortcut({
    combo: "?",
    description: t.commandPalette?.showShortcuts ?? "Show keyboard shortcuts",
    handler: () => {
      setPaletteOpen(false);
      setHelpOpen((o) => !o);
    },
    scope,
  });
  useShortcut({
    combo: "[",
    description: t.commandPalette?.toggleSidebar ?? "Toggle sidebar",
    handler: toggleCollapsed,
    scope,
  });
  // "[" needs AltGr on many European layouts (German, French, Spanish,
  // Italian), and matchesCombo rejects Alt-bearing events for bare-key
  // combos (that guard protects Cmd+[ browser-back). mod+b is the
  // layout-safe companion binding — the VS Code/Slack sidebar convention.
  useShortcut({
    combo: "mod+b",
    description: t.commandPalette?.toggleSidebar ?? "Toggle sidebar",
    handler: toggleCollapsed,
    scope,
  });

  // The shortcut registry drops events from editable targets, and while the
  // palette is open focus sits in its autoFocus search input — so the
  // registered mod+k toggle can open the palette but never close it. This
  // listener (attached only while open) restores press-⌘K-again-to-dismiss.
  // The defaultPrevented check defers to the registry for the rare case
  // where focus has left the input and the registered toggle already
  // handled the event.
  useEffect(() => {
    if (!paletteOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.repeat) return;
      if (!matchesCombo(event, "mod+k")) return;
      event.preventDefault();
      setPaletteOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [paletteOpen]);

  return (
    <>
      <CommandPalette
        embeddedChat={embeddedChat}
        onClose={() => setPaletteOpen(false)}
        onShowShortcuts={() => {
          setPaletteOpen(false);
          setHelpOpen(true);
        }}
        open={paletteOpen}
        pluginItems={pluginItems}
        sections={sections}
        toggleCollapsed={toggleCollapsed}
      />
      <ShortcutHelp onClose={() => setHelpOpen(false)} open={helpOpen} />
    </>
  );
}

/**
 * Remounts the entire routed page tree when the global management profile
 * changes. Pages load their data on mount; without this, a page opened
 * under profile A would keep showing A's state while writes (via the
 * fetchJSON ?profile= injection) silently targeted the newly selected
 * profile B — the exact stale-target footgun the switcher exists to kill.
 * Keying by profile resets every page's local state so it refetches under
 * the new scope. The persistent ChatPage host below handles its own
 * remount (channel keyed on scopedProfile).
 */
function ProfileKeyedRoutes({ children }: { children: ReactNode }) {
  const { profile } = useProfileScope();
  return <div key={profile || "__own__"} className="contents">{children}</div>;
}
