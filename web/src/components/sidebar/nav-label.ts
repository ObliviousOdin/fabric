import type { Translations } from "@/i18n/types";
import { appNavLabel } from "@/lib/app-nav-label";
import type { NavItem } from "./nav-model";

/**
 * Resolve a nav item's display label: built-ins carry a `labelKey` into
 * `t.app.nav` (falling back to the static English label), plugin items use
 * their manifest label as-is. Shared by the sidebar and the command palette
 * so the lookup (and its type-erasing cast) lives in one place.
 */
export function navItemLabel(item: NavItem, t: Translations): string {
  return appNavLabel(item.labelKey, item.label, t);
}
