const ACCOUNT_CHOICE_PROVIDERS = new Set(["openai-codex", "xai-oauth"]);

const MANAGED_PROVIDER_DOCS: Record<string, string> = {
  "openai-codex":
    "https://obliviousodin.github.io/fabric/guides/chatgpt-codex-subscription",
  "xai-oauth":
    "https://obliviousodin.github.io/fabric/guides/xai-grok-oauth",
};

export function supportsAccountOwnershipChoice(providerId: string): boolean {
  return ACCOUNT_CHOICE_PROVIDERS.has(providerId);
}

export function managedProviderDocsUrl(providerId: string): string {
  return MANAGED_PROVIDER_DOCS[providerId] ?? "https://obliviousodin.github.io/fabric/";
}
