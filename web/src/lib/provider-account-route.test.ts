import { describe, expect, it } from "vitest";

import {
  managedProviderDocsUrl,
  supportsAccountOwnershipChoice,
} from "./provider-account-route";

describe("provider account routing", () => {
  it("asks who owns subscription-backed ChatGPT and Grok connections", () => {
    expect(supportsAccountOwnershipChoice("openai-codex")).toBe(true);
    expect(supportsAccountOwnershipChoice("xai-oauth")).toBe(true);
    expect(supportsAccountOwnershipChoice("nous")).toBe(false);
  });

  it("routes managed providers to the Fabric-owned setup guides", () => {
    expect(managedProviderDocsUrl("openai-codex")).toContain(
      "obliviousodin.github.io/fabric/guides/chatgpt-codex-subscription",
    );
    expect(managedProviderDocsUrl("xai-oauth")).toContain(
      "obliviousodin.github.io/fabric/guides/xai-grok-oauth",
    );
  });
});
