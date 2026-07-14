import { describe, expect, it } from "vitest";

import { ja } from "@/i18n/ja";
import { resolvePageTitle } from "@/lib/resolve-page-title";
import { appNavLabel } from "./app-nav-label";

describe("enterprise IA localization fallback", () => {
  it.each([
    ["conversations", "sessions"],
    ["agents", "profiles"],
    ["automations", "cron"],
    ["insights", "analytics"],
    ["integrations", "plugins"],
    ["aiRuntime", "models"],
    ["advanced", "config"],
    ["help", "documentation"],
  ])("reuses the translated legacy %s concept", (enterpriseKey, legacyKey) => {
    expect(appNavLabel(enterpriseKey, "English fallback", ja)).toBe(
      (ja.app.nav as Record<string, string>)[legacyKey],
    );
  });

  it.each([
    ["/admin/integrations/skills", "skills"],
    ["/admin/security-access/secrets", "keys"],
    ["/admin/advanced/logs", "logs"],
  ])("localizes the nested utility route %s", (path, legacyKey) => {
    expect(resolvePageTitle(path, ja, [])).toBe(
      (ja.app.nav as Record<string, string>)[legacyKey],
    );
  });
});
