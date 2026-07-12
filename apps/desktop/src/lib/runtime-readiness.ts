export interface EgressStatusSnapshot {
  allowed_private_cidr_count?: number
  available?: boolean
  mode?: 'air_gapped' | 'local_ai' | 'online' | 'unknown'
  reason?: null | string
  scope?: string
  status?: 'available' | 'unavailable'
}

export interface SetupStatusSnapshot {
  egress?: EgressStatusSnapshot
  error?: string
  provider_configured?: boolean
}

export interface RuntimeCheckSnapshot {
  egress?: EgressStatusSnapshot
  error?: string
  error_code?: string
  ok?: boolean
}

export interface RuntimeReadinessSignals {
  setup: null | SetupStatusSnapshot
  setupError: null | string
  runtime: null | RuntimeCheckSnapshot
  runtimeError: null | string
}

export interface RuntimeReadinessOptions {
  defaultReason?: string
  profile?: string
  requestedProvider?: string
  sessionId?: string
  unknownReady?: boolean
}

export interface RuntimeReadinessResult {
  checksDisagree: boolean
  ready: boolean
  reason: null | string
  source: 'fallback' | 'runtime_check' | 'setup_status'
}

export type RuntimeReadinessRequester = <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>

const DEFAULT_NOT_READY_REASON = 'Add a provider credential before sending your first message.'

function toErrorMessage(error: unknown): null | string {
  if (error instanceof Error) {
    return error.message
  }

  if (typeof error === 'string') {
    return error
  }

  if (error === null || error === undefined) {
    return null
  }

  return String(error)
}

function normalizeMessage(value: null | string | undefined): null | string {
  const next = value?.trim()

  return next ? next : null
}

async function requestWithFallback<T>(
  requestGateway: RuntimeReadinessRequester,
  method: string,
  params?: Record<string, unknown>
): Promise<{ error: null | string; value: null | T }> {
  try {
    return { error: null, value: await requestGateway<T>(method, params) }
  } catch (error) {
    return { error: toErrorMessage(error), value: null }
  }
}

export async function fetchRuntimeReadinessSignals(
  requestGateway: RuntimeReadinessRequester,
  requestedProvider?: string,
  scope: Pick<RuntimeReadinessOptions, 'profile' | 'sessionId'> = {}
): Promise<RuntimeReadinessSignals> {
  const commonParams: Record<string, unknown> = {}

  if (scope.sessionId?.trim()) {
    commonParams.session_id = scope.sessionId.trim()
  } else if (scope.profile?.trim()) {
    commonParams.profile = scope.profile.trim()
  }

  const setupParams = Object.keys(commonParams).length > 0 ? commonParams : undefined
  const runtimeParams: Record<string, unknown> = { ...commonParams }

  if (requestedProvider?.trim()) {
    runtimeParams.provider = requestedProvider.trim()
  }

  const effectiveRuntimeParams = Object.keys(runtimeParams).length > 0 ? runtimeParams : undefined

  const [setup, runtime] = await Promise.all([
    requestWithFallback<SetupStatusSnapshot>(requestGateway, 'setup.status', setupParams),
    requestWithFallback<RuntimeCheckSnapshot>(requestGateway, 'setup.runtime_check', effectiveRuntimeParams)
  ])

  return {
    setup: setup.value,
    setupError: setup.error,
    runtime: runtime.value,
    runtimeError: runtime.error
  }
}

export function interpretRuntimeReadiness(
  signals: RuntimeReadinessSignals,
  options: RuntimeReadinessOptions = {}
): RuntimeReadinessResult {
  const defaultReason = options.defaultReason ?? DEFAULT_NOT_READY_REASON
  const unknownReady = options.unknownReady ?? false

  const setupConfigured =
    typeof signals.setup?.provider_configured === 'boolean' ? Boolean(signals.setup.provider_configured) : undefined

  const runtimeOk = typeof signals.runtime?.ok === 'boolean' ? Boolean(signals.runtime.ok) : undefined
  const runtimeFailure = normalizeMessage(signals.runtime?.error) ?? normalizeMessage(signals.runtimeError)
  const setupFailure = normalizeMessage(signals.setupError)
  const egress = signals.runtime?.egress ?? signals.setup?.egress

  if (egress?.available === false) {
    const mode = normalizeMessage(egress.mode) ?? 'unknown'
    const reason = normalizeMessage(egress.reason) ?? 'egress_policy_unavailable'

    return {
      checksDisagree: false,
      ready: false,
      reason: `AI egress mode ${mode} is unavailable: ${reason}.`,
      source: signals.runtime ? 'runtime_check' : 'setup_status'
    }
  }

  const checksDisagree =
    typeof setupConfigured === 'boolean' && typeof runtimeOk === 'boolean' && setupConfigured !== runtimeOk

  if (typeof runtimeOk === 'boolean') {
    if (runtimeOk) {
      return {
        checksDisagree,
        ready: true,
        reason: null,
        source: 'runtime_check'
      }
    }

    let reason = runtimeFailure ?? defaultReason

    if (checksDisagree && setupConfigured) {
      reason = `${reason} setup.status reports configured credentials, but runtime resolution still failed.`
    }

    return {
      checksDisagree,
      ready: false,
      reason,
      source: 'runtime_check'
    }
  }

  if (typeof setupConfigured === 'boolean') {
    return {
      checksDisagree: false,
      ready: setupConfigured,
      reason: setupConfigured ? null : (runtimeFailure ?? setupFailure ?? defaultReason),
      source: 'setup_status'
    }
  }

  return {
    checksDisagree: false,
    ready: unknownReady,
    reason: unknownReady ? null : (runtimeFailure ?? setupFailure ?? defaultReason),
    source: 'fallback'
  }
}

export async function evaluateRuntimeReadiness(
  requestGateway: RuntimeReadinessRequester,
  options: RuntimeReadinessOptions = {}
): Promise<RuntimeReadinessResult> {
  const signals = await fetchRuntimeReadinessSignals(requestGateway, options.requestedProvider, options)

  return interpretRuntimeReadiness(signals, options)
}
