const MANAGED_PROVIDER_META: Record<string, { docsUrl: string }> = {
  'openai-codex': {
    docsUrl: 'https://obliviousodin.github.io/fabric/guides/chatgpt-codex-subscription'
  },
  'xai-oauth': {
    docsUrl: 'https://obliviousodin.github.io/fabric/guides/xai-grok-oauth'
  }
}

export function supportsAccountOwnershipChoice(providerId: string): boolean {
  return Object.hasOwn(MANAGED_PROVIDER_META, providerId)
}

export function managedProviderDocsUrl(providerId: string): string {
  return MANAGED_PROVIDER_META[providerId]?.docsUrl ?? 'https://obliviousodin.github.io/fabric/'
}
