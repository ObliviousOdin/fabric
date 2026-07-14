import type { Translations } from "@/i18n/types";
import { DEFAULT_ROUTE, routeForPath } from "@/app/routes";
import { appNavLabel } from "@/lib/app-nav-label";

export function resolvePageTitle(
  pathname: string,
  t: Translations,
  pluginTabs: { path: string; label: string }[],
): string {
  const normalized = pathname.replace(/\/$/, "") || "/";
  const plugin = pluginTabs.find((p) => p.path === normalized);
  if (plugin) {
    return plugin.label;
  }

  const route = routeForPath(normalized === "/" ? DEFAULT_ROUTE : normalized);
  if (route?.nav) {
    return appNavLabel(route.nav.labelKey, route.nav.label, t);
  }
  if (route?.title) {
    return appNavLabel(route.titleKey, route.title, t);
  }

  // Derive a title for nested utility routes that deliberately stay out of
  // the primary nav: "/admin/integrations/skills" → "Skills".
  const canonical = route?.path ?? normalized;
  const segment = canonical.slice(canonical.lastIndexOf("/") + 1);
  if (segment) {
    return (segment.charAt(0).toUpperCase() + segment.slice(1)).replace(
      /-/g,
      " ",
    );
  }
  return t.app.webUi;
}
