import type { Translations } from "@/i18n/types";

const LEGACY_NAV_KEYS: Record<string, string> = {
  advanced: "config",
  agents: "profiles",
  aiRuntime: "models",
  automations: "cron",
  conversations: "sessions",
  help: "documentation",
  insights: "analytics",
  integrations: "plugins",
  securityAccess: "keys",
};

/** Resolve new IA keys first, then legacy nav keys, then stable English. */
export function appNavLabel(
  labelKey: string | undefined,
  fallback: string,
  t: Translations,
): string {
  if (!labelKey) return fallback;
  const enterprise = t.app.enterpriseNav as
    | Record<string, string>
    | undefined;
  const legacyKey = LEGACY_NAV_KEYS[labelKey] ?? labelKey;
  return (
    enterprise?.[labelKey] ??
    (t.app.nav as Record<string, string>)[legacyKey] ??
    fallback
  );
}
