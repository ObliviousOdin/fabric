import { getGlobalModelOptions, type HermesGateway, type ModelOptionsResponse } from '@/hermes'

interface ModelOptionsRequest {
  /** When false, include ambient/unconfigured providers (onboarding/setup
   *  surfaces). Chat pickers default to true so only explicitly configured
   *  providers are listed (#56974). */
  explicitOnly?: boolean
  gateway?: HermesGateway
  /** Explicit REST profile for profile-pinned multi-step flows. Ignored when a
   *  gateway/session supplies the ownership scope. */
  profile?: string
  refresh?: boolean
  sessionId?: null | string
}

export function requestModelOptions({
  explicitOnly = true,
  gateway,
  profile,
  refresh = false,
  sessionId
}: ModelOptionsRequest): Promise<ModelOptionsResponse> {
  if (gateway) {
    const params: Record<string, unknown> = {}

    if (sessionId) {
      params.session_id = sessionId
    }

    if (refresh) {
      params.refresh = true
    }

    if (explicitOnly) {
      params.explicit_only = true
    }

    return gateway.request<ModelOptionsResponse>('model.options', params)
  }

  const options = { explicitOnly, ...(refresh ? { refresh: true } : {}) }

  return profile ? getGlobalModelOptions(options, profile) : getGlobalModelOptions(options)
}
