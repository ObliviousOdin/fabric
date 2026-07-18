import { atom } from 'nanostores'

import { brandText, desktopBrand } from '@/brand'
import {
  cancelOAuthSession,
  configureLocalOllama,
  createProviderManagedRequest,
  discoverLocalOllama,
  getGlobalModelOptions,
  getProviderAccount,
  getRecommendedDefaultModel,
  listOAuthProviders,
  pollOAuthSession,
  recordProviderAccountHandoff,
  setEnvVar,
  setModelAssignment,
  startOAuthLogin,
  submitOAuthCode,
  validateProviderCredential
} from '@/hermes'
import { supportsAccountOwnershipChoice } from '@/lib/provider-account-route'
import { evaluateRuntimeReadiness, type RuntimeReadinessResult } from '@/lib/runtime-readiness'
import { notify, notifyError } from '@/store/notifications'
import { $activeGatewayProfile, normalizeProfileKey } from '@/store/profile'
import type { ModelOptionProvider, OAuthProvider, OAuthStartResponse } from '@/types/hermes'

type PkceStart = Extract<OAuthStartResponse, { flow: 'pkce' }>
type DeviceStart = Extract<OAuthStartResponse, { flow: 'device_code' }>

export type OnboardingMode = 'apikey' | 'oauth' | 'ollama'

export type OnboardingFlow =
  | { status: 'idle' }
  | { profile: string; provider: OAuthProvider; status: 'choosing_account' }
  | {
      message?: string
      profile: string
      provider: OAuthProvider
      requesting?: boolean
      status: 'managed_info'
    }
  | { profile: string; provider: OAuthProvider; status: 'starting' }
  | { code: string; profile: string; provider: OAuthProvider; start: PkceStart; status: 'awaiting_user' }
  | { copied: boolean; profile: string; provider: OAuthProvider; start: DeviceStart; status: 'polling' }
  | { profile: string; provider: OAuthProvider; start: OAuthStartResponse; status: 'submitting' }
  | { copied: boolean; profile: string; provider: OAuthProvider; status: 'external_pending' }
  | { profile: string; provider: OAuthProvider; status: 'success' }
  | {
      // After successful credential acquisition, before completing
      // onboarding: show the user which model they're getting and let
      // them change it. providerSlug is the model.options slug for the
      // just-authenticated provider (used to persist the chosen model
      // via /api/model/set). The change-model UI uses the existing
      // ModelPickerDialog, which fetches its own model list from
      // /api/model/options — no need to cache the list here.
      currentModel: string
      label: string
      profile: string
      providerSlug: string
      saving: boolean
      status: 'confirming_model'
    }
  | {
      // A custom endpoint can advertise several models. Keep its connection
      // details in renderer memory and require an explicit model choice before
      // writing any assignment. The one-model case keeps its existing fast
      // path and never enters this state.
      apiKey: string
      baseUrl: string
      currentModel: string
      message?: string
      models: string[]
      localProvider: 'custom' | 'ollama'
      profile: string
      saving: boolean
      status: 'confirming_local_model'
    }
  | {
      message: string
      profile?: string
      provider?: OAuthProvider
      start?: OAuthStartResponse
      status: 'error'
      takeoverAvailable?: boolean
    }

export interface DesktopOnboardingState {
  /** null until the first runtime check resolves. Seeded from localStorage so
   *  returning users skip the boot overlay entirely instead of flashing it
   *  every reload. */
  configured: boolean | null
  flow: OnboardingFlow
  mode: OnboardingMode
  providers: null | OAuthProvider[]
  reason: null | string
  requested: boolean
  /** True when the user explicitly chose "I'll choose a provider later" on the
   *  first-run picker. Persisted to localStorage so the blocking overlay never
   *  re-nags on subsequent launches — the user can connect a provider any time
   *  from Settings → Providers (or the model picker's "Add provider"). Distinct
   *  from `configured`: the app still has no usable provider, so chat won't work
   *  until one is connected; we just stop forcing the choice up front. */
  firstRunSkipped: boolean
  /** True when the user explicitly opened the provider selector to add /
   *  switch providers from an already-configured app (e.g. via the model
   *  picker's "Add provider" button). Forces the overlay to show the picker
   *  even when configured === true, and adds a close affordance. */
  manual: boolean
  /** True when the overlay was opened specifically to configure a local /
   *  custom OpenAI-compatible endpoint (e.g. from Settings → Model's "Set up
   *  custom endpoint"). Forces the API-key form with the local option
   *  preselected instead of the OAuth picker. */
  localEndpoint: boolean
}

export interface OnboardingContext {
  onCompleted?: () => void
  requestGateway: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

const CONFIGURED_CACHE_KEY = 'hermes-desktop-onboarded-v1'
const SKIP_CACHE_KEY = 'fabric-onboarding-skipped-v1'
const POLL_MS = 2000
const COPY_FLASH_MS = 1500
export const DEFAULT_ONBOARDING_REASON = 'No inference provider is configured.'
export const DEFAULT_MANUAL_ONBOARDING_REASON = 'Add or switch inference provider.'

function readCachedConfigured(): boolean | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    return window.localStorage.getItem(CONFIGURED_CACHE_KEY) === '1' ? true : null
  } catch {
    return null
  }
}

function writeCachedConfigured(value: boolean) {
  if (typeof window === 'undefined') {
    return
  }

  try {
    if (value) {
      window.localStorage.setItem(CONFIGURED_CACHE_KEY, '1')
    } else {
      window.localStorage.removeItem(CONFIGURED_CACHE_KEY)
    }
  } catch {
    // localStorage unavailable — degrade silently.
  }
}

function readCachedSkipped(): boolean {
  if (typeof window === 'undefined') {
    return false
  }

  try {
    return window.localStorage.getItem(SKIP_CACHE_KEY) === '1'
  } catch {
    return false
  }
}

function writeCachedSkipped(value: boolean) {
  if (typeof window === 'undefined') {
    return
  }

  try {
    if (value) {
      window.localStorage.setItem(SKIP_CACHE_KEY, '1')
    } else {
      window.localStorage.removeItem(SKIP_CACHE_KEY)
    }
  } catch {
    // localStorage unavailable — degrade silently.
  }
}

const INITIAL: DesktopOnboardingState = {
  configured: readCachedConfigured(),
  flow: { status: 'idle' },
  mode: 'oauth',
  providers: null,
  reason: null,
  requested: false,
  firstRunSkipped: readCachedSkipped(),
  manual: false,
  localEndpoint: false
}

export const $desktopOnboarding = atom<DesktopOnboardingState>(INITIAL)

let pollTimer: number | null = null
let pollInFlightEpoch: number | null = null
let providersRefreshPromise: null | Promise<void> = null
// Invalidates async work from an OAuth flow when the user closes the overlay,
// switches setup modes, or starts a different provider. Clearing the interval
// alone is insufficient: a /start or /poll request may already be in flight and
// would otherwise revive the flow after the user left it.
let oauthFlowEpoch = 0
// Managed-request work has its own epoch. Provider/profile equality is not
// enough: leaving and returning to the same card is an ABA transition, and a
// late first request must not open its mailto handoff in the new visit.
let managedRequestEpoch = 0
// The local endpoint probe is also asynchronous. Invalidate its epoch whenever
// the user closes or changes setup so a late /v1/models response cannot revive
// a cancelled flow or persist an arbitrary model.
let localEndpointFlowEpoch = 0

const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e))

const patch = (update: Partial<DesktopOnboardingState>) =>
  $desktopOnboarding.set({ ...$desktopOnboarding.get(), ...update })

const setFlow = (flow: OnboardingFlow) => patch(flow.status === 'idle' ? { flow } : { flow, reason: null })

const sessionIdFor = (flow: OnboardingFlow) => ('start' in flow && flow.start ? flow.start.session_id : undefined)

const providerIdFor = (flow: OnboardingFlow) => ('provider' in flow && flow.provider ? flow.provider.id : undefined)

const profileFor = (flow: OnboardingFlow) =>
  'profile' in flow && flow.profile ? flow.profile : normalizeProfileKey($activeGatewayProfile.get())

function shellArgument(value: string): string {
  return /^[a-zA-Z0-9_-]+$/.test(value) ? value : `'${value.replaceAll("'", `'"'"'`)}'`
}

function scopeExternalProviderCommand(provider: OAuthProvider, profile: string): OAuthProvider {
  const command = provider.cli_command.trim()

  // Commands owned by Fabric/Hermes honor the global profile selector. The
  // remaining external commands (for example `copilot /login` and
  // `claude setup-token`) own their credentials outside Fabric and must remain
  // byte-for-byte unchanged.
  if (!/^(?:hermes|fabric)(?:\s|$)/.test(command)) {
    return provider
  }

  const scopedCommand = command.replace(/^(hermes|fabric)(?=\s|$)/, `$1 --profile ${shellArgument(profile)}`)

  return { ...provider, cli_command: scopedCommand }
}

let observedGatewayProfile = normalizeProfileKey($activeGatewayProfile.get())

$activeGatewayProfile.subscribe(value => {
  const profile = normalizeProfileKey(value)

  if (profile === observedGatewayProfile) {
    return
  }

  observedGatewayProfile = profile
  localEndpointFlowEpoch += 1

  // A pending local-endpoint choice owns credentials for the profile where it
  // was probed. Drop that in-memory state as soon as the live profile changes;
  // the new profile returns to its own setup form instead of inheriting it.
  if ($desktopOnboarding.get().flow.status === 'confirming_local_model') {
    setFlow({ status: 'idle' })
  }
})

function clearPoll() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function cancelSessionBestEffort(providerId: string, sessionId: string, profile: string) {
  try {
    void cancelOAuthSession(providerId, sessionId, profile).catch(() => undefined)
  } catch {
    // The desktop bridge may already be gone during teardown. Cancellation is
    // best-effort here; local flow state still needs to close synchronously.
  }
}

function stopActiveOAuthFlow() {
  oauthFlowEpoch += 1
  clearPoll()
  pollInFlightEpoch = null

  const flow = $desktopOnboarding.get().flow
  const sessionId = sessionIdFor(flow)
  const providerId = providerIdFor(flow)

  if (sessionId && providerId) {
    cancelSessionBestEffort(providerId, sessionId, profileFor(flow))
  }
}

function stopActiveSetupFlow() {
  stopActiveOAuthFlow()
  managedRequestEpoch += 1
  localEndpointFlowEpoch += 1
}

async function checkRuntime(
  ctx: OnboardingContext,
  requestedProvider?: string,
  profile = normalizeProfileKey($activeGatewayProfile.get())
): Promise<RuntimeReadinessResult> {
  return evaluateRuntimeReadiness(ctx.requestGateway, {
    defaultReason: DEFAULT_ONBOARDING_REASON,
    profile,
    requestedProvider,
    unknownReady: false
  })
}

function shouldPreserveConfiguredOnFallback(runtime: RuntimeReadinessResult, state: DesktopOnboardingState): boolean {
  // A fallback result means both runtime probes were non-authoritative
  // (transport timeout/disconnect). Keep a previously verified configured
  // state instead of forcing the blocking onboarding overlay.
  return runtime.source === 'fallback' && state.configured === true && !state.requested
}

function notifyReady(provider: string) {
  notify({ kind: 'success', title: `${desktopBrand.productName} is ready`, message: `${provider} connected.` })
}

// Human-friendly labels for tools auto-routed through a managed Tool Gateway,
// mirroring fabric_cli/nous_subscription._GATEWAY_TOOL_LABELS so the GUI and
// CLI describe the same thing.
const GATEWAY_TOOL_LABELS: Record<string, string> = {
  browser: 'browser automation',
  image_gen: 'image generation',
  tts: 'text-to-speech',
  video_gen: 'video generation',
  web: 'web search & extract'
}

// When a provider auto-routes unconfigured tools through the Tool Gateway,
// tell the user which ones — same information the CLI prints. Silent
// when nothing changed (subscriber already configured, has own keys, etc.).
function notifyGatewayTools(tools: string[] | undefined) {
  if (!tools || tools.length === 0) {
    return
  }

  const labels = tools.map(t => GATEWAY_TOOL_LABELS[t] ?? t)
  const list = labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`

  notify({
    durationMs: 8000,
    kind: 'info',
    message: `${list} now use the configured managed route.`,
    title: 'Managed tool routes enabled'
  })
}

// After credentials are persisted, ask the backend which provider+models
// are now authenticated. Pick the first curated model for the matching
// provider as a sensible default, persist it via /api/model/set, and
// transition to the model-confirmation step. If anything goes wrong
// fetching options (no providers returned, network error), the caller
// falls through to completing onboarding without showing the confirm
// card — the user gets the undefined-model auto-selection behaviour
// we had before, which works but is surprising. The confirm step is
// opportunistic polish, not a hard requirement for onboarding.
async function fetchProviderDefaultModel(
  preferredSlugs: string[],
  profile: string
): Promise<null | { providerSlug: string; defaultModel: string }> {
  let options

  try {
    options = await getGlobalModelOptions({ includeUnconfigured: true, explicitOnly: false }, profile)
  } catch {
    return null
  }

  const providers = options?.providers ?? []

  if (providers.length === 0) {
    return null
  }

  // Try each preferred slug (lowercased), fall back to the first provider
  // returned (model.options orders by recency / authenticated state, so
  // the just-authenticated provider is usually first anyway).
  const lower = preferredSlugs.map(s => s.toLowerCase())

  const matched =
    providers.find((p: ModelOptionProvider) => lower.includes(String(p.slug).toLowerCase())) ?? providers[0]

  const models = matched.models ?? []

  if (models.length === 0) {
    return null
  }

  // Prefer the backend's recommended default — it mirrors the curation
  // `fabric model` does (for Nous it honors the user's free/paid tier, so a
  // free user gets a free model rather than a paid default like opus). Fall
  // back to the first curated model if the endpoint can't resolve one.
  let defaultModel = String(models[0])

  try {
    const recommended = await getRecommendedDefaultModel(String(matched.slug), profile)

    if (recommended.model && models.map(String).includes(recommended.model)) {
      defaultModel = recommended.model
    } else if (recommended.model) {
      // Recommended model isn't in the curated options list (e.g. a Portal
      // free-recommendation the picker list didn't include); trust it anyway.
      defaultModel = recommended.model
    }
  } catch {
    // Endpoint unavailable — keep models[0]. Non-fatal: the confirm card still
    // shows and the user can change it.
  }

  return {
    providerSlug: String(matched.slug),
    defaultModel
  }
}

// After OAuth/API-key success: reload the backend env, verify runtime,
// then either show the model-confirm step or fall straight through to
// completion if we can't determine a default.
//
// onFail receives the runtime-readiness `reason` from checkRuntime so
// the caller can fold it into a user-facing error — same contract as
// reloadAndConnect used to have (which this replaces).
interface ModelConfirmCompletionOptions {
  ignoreRuntimeGate?: boolean
  oauthEpoch?: number
  profile: string
}

async function completeWithModelConfirm(
  ctx: OnboardingContext,
  providerLabel: string,
  preferredSlugs: string[],
  onFail: (reason: null | string) => void,
  options: ModelConfirmCompletionOptions
) {
  const { ignoreRuntimeGate = false, oauthEpoch, profile } = options
  const isCurrent = () => oauthEpoch === undefined || oauthEpoch === oauthFlowEpoch

  if (!isCurrent()) {
    return
  }

  await ctx.requestGateway('reload.env', { profile }).catch(() => undefined)

  if (!isCurrent()) {
    return
  }

  const defaults = await fetchProviderDefaultModel(preferredSlugs, profile)

  if (!isCurrent()) {
    return
  }

  if (defaults) {
    // Persist the chosen provider/model before the runtime gate so a stale
    // config provider (e.g. anthropic from a prior failed setup) cannot make
    // setup.runtime_check validate the wrong backend after a fresh OAuth login.
    try {
      const res = await setModelAssignment(
        {
          scope: 'main',
          provider: defaults.providerSlug,
          model: defaults.defaultModel
        },
        profile
      )

      notifyGatewayTools(res.gateway_tools)
    } catch {
      // Persistence failed — still run the scoped runtime check below and
      // show the confirm card so the user can pick something explicitly.
    }
  }

  if (!isCurrent()) {
    return
  }

  const runtime = await checkRuntime(ctx, preferredSlugs[0], profile)

  if (!isCurrent()) {
    return
  }

  if (!runtime.ready && !ignoreRuntimeGate) {
    onFail(runtime.reason)

    return
  }

  if (!defaults) {
    // Couldn't get a sensible default — proceed without confirm step.
    if (!completeDesktopOnboarding(profile)) {
      return
    }

    notifyReady(providerLabel)
    ctx.onCompleted?.()

    return
  }

  setFlow({
    status: 'confirming_model',
    providerSlug: defaults.providerSlug,
    currentModel: defaults.defaultModel,
    label: providerLabel,
    profile,
    saving: false
  })
}

function providerResolutionFailure(reason: null | string) {
  const detail = reason?.trim()

  return detail
    ? brandText(`Connected, but Fabric still cannot resolve a usable provider. ${detail}`)
    : brandText('Connected, but Fabric still cannot resolve a usable provider.')
}

async function refreshProviders() {
  if (providersRefreshPromise) {
    await providersRefreshPromise

    return
  }

  providersRefreshPromise = (async () => {
    try {
      const { providers } = await listOAuthProviders()
      patch({ mode: providers.length > 0 ? 'oauth' : 'apikey', providers })
    } catch {
      patch({ mode: 'apikey', providers: [] })
    } finally {
      providersRefreshPromise = null
    }
  })()

  await providersRefreshPromise
}

export function requestDesktopOnboarding(reason = DEFAULT_ONBOARDING_REASON) {
  patch({ reason: reason.trim() || DEFAULT_ONBOARDING_REASON, requested: true })
}

// Open the onboarding provider selector on demand from an already-configured
// app — e.g. the model picker's "Add provider" button. Reuses the entire
// onboarding flow (OAuth rows, API-key form, model-confirm) instead of
// duplicating provider UI. Sets manual=true so the overlay shows the picker
// even though configured===true, and refreshes the provider list.
export function startManualOnboarding(reason: null | string = DEFAULT_MANUAL_ONBOARDING_REASON) {
  stopActiveSetupFlow()
  patch({
    manual: true,
    requested: true,
    localEndpoint: false,
    // `null` opts out of the prompt banner entirely (e.g. when the user already
    // picked a specific provider and we auto-start its sign-in).
    reason: reason ? reason.trim() || DEFAULT_ONBOARDING_REASON : null,
    flow: { status: 'idle' }
  })
  void refreshProviders()
}

// Open the onboarding overlay directly on the local / custom endpoint form
// (URL + optional API key), bypassing the OAuth picker. Used by Settings →
// Model's "Set up custom endpoint" so it lands on a form that can actually
// configure the endpoint instead of dead-ending on the OAuth provider list
// (`custom` is not an OAuth provider, so the generic manual flow would just
// re-show the picker — the original "booted back to the first screen" loop).
export function startManualLocalEndpoint(reason: null | string = null) {
  stopActiveSetupFlow()
  pendingProviderOAuth = null
  patch({
    manual: true,
    requested: true,
    localEndpoint: true,
    mode: 'apikey',
    reason: reason ? reason.trim() || DEFAULT_ONBOARDING_REASON : null,
    flow: { status: 'idle' }
  })
}

// One-shot hand-off used when the dedicated Providers settings page launches a
// specific provider's sign-in: we open the manual onboarding overlay AND
// remember which provider to start, so the overlay drives that exact OAuth
// flow instead of re-showing the picker the user just clicked through.
// Module-level (not store state) because it's consumed immediately on the next
// overlay render and never needs to persist or re-render anything itself.
let pendingProviderOAuth: null | { id: string; profile: string } = null

export function startManualProviderOAuth(providerId: string, reason: null | string = null) {
  pendingProviderOAuth = {
    id: providerId,
    profile: normalizeProfileKey($activeGatewayProfile.get())
  }
  startManualOnboarding(reason)
}

// Read the pending provider id without clearing it. The overlay only clears it
// (via clearPendingProviderOAuth) once it has actually launched that provider,
// so a transient empty/failed provider fetch doesn't drop the hand-off and the
// deep-link can still auto-start after the list loads.
export function peekPendingProviderOAuth(): null | string {
  return pendingProviderOAuth?.id ?? null
}

export function clearPendingProviderOAuth(): null | string {
  const profile = pendingProviderOAuth?.profile ?? null
  pendingProviderOAuth = null

  return profile
}

// Dismiss a manually-opened provider selector without touching the existing
// (working) configuration. Only valid in the manual path — the unconfigured
// first-run flow has no close affordance because the app can't run yet.
export function closeManualOnboarding() {
  stopActiveSetupFlow()
  pendingProviderOAuth = null

  patch({ manual: false, requested: false, localEndpoint: false, flow: { status: 'idle' } })
}

export function completeDesktopOnboarding(expectedProfile = normalizeProfileKey($activeGatewayProfile.get())): boolean {
  if (normalizeProfileKey($activeGatewayProfile.get()) !== normalizeProfileKey(expectedProfile)) {
    // The completed ceremony belongs to a profile that is no longer active.
    // Its backend credentials stay where they were written, but it must not
    // mark the newly active renderer/profile configured or invoke its
    // completion callback. Return to the current profile's neutral setup view.
    stopActiveSetupFlow()
    setFlow({ status: 'idle' })

    return false
  }

  clearPoll()
  localEndpointFlowEpoch += 1
  writeCachedConfigured(true)
  // A real provider is now connected, so any earlier "choose later" skip is
  // moot — clear it so the flag never lingers in a configured install.
  writeCachedSkipped(false)
  $desktopOnboarding.set({
    configured: true,
    flow: { status: 'idle' },
    mode: 'oauth',
    providers: null,
    reason: null,
    requested: false,
    firstRunSkipped: false,
    manual: false,
    localEndpoint: false
  })

  return true
}

// "I'll choose a provider later" on the first-run picker. Persists the skip so
// the blocking overlay never re-nags on future launches, and dismisses it now
// so the user lands in the app. Chat won't work until a provider is connected
// (from Settings → Providers or the model picker's "Add provider") — this only
// stops forcing the choice up front. Distinct from completeDesktopOnboarding,
// which marks the app actually configured.
export function dismissFirstRunOnboarding() {
  stopActiveSetupFlow()
  writeCachedSkipped(true)
  patch({ firstRunSkipped: true, requested: false, manual: false, localEndpoint: false, flow: { status: 'idle' } })
}

export function setOnboardingMode(mode: OnboardingMode) {
  stopActiveSetupFlow()
  patch({ mode, flow: { status: 'idle' } })
}

export async function refreshOnboarding(ctx: OnboardingContext) {
  // Manual mode (user opened the selector from a working app): never
  // auto-dismiss on runtime-ready — the whole point is to let them add /
  // switch a provider while already configured. Just ensure the provider
  // list is loaded and show the picker.
  if ($desktopOnboarding.get().manual) {
    await refreshProviders()

    return false
  }

  const profile = normalizeProfileKey($activeGatewayProfile.get())
  const runtime = await checkRuntime(ctx, undefined, profile)

  if (runtime.ready) {
    const completed = completeDesktopOnboarding(profile)

    if (completed) {
      ctx.onCompleted?.()
    }

    return completed
  }

  const state = $desktopOnboarding.get()

  if (shouldPreserveConfiguredOnFallback(runtime, state)) {
    // Gateway probes timed out but the user was already configured — don't
    // downgrade to the blocking onboarding overlay. Surface a non-blocking
    // notification with a stable id so repeated calls during an outage dedup
    // instead of stacking toasts.
    notify({
      id: 'runtime-not-ready',
      kind: 'error',
      title: 'Runtime not ready',
      message: brandText(
        'Fabric could not verify the running backend on startup. Some features may be unavailable until the gateway is reachable.'
      )
    })

    return false
  }

  const reason = runtime.reason || state.reason || DEFAULT_ONBOARDING_REASON

  writeCachedConfigured(false)
  patch({ configured: false, reason })

  if (state.providers !== null && !state.requested) {
    return false
  }

  await refreshProviders()

  return false
}

// Open a sign-in URL through exactly one authority. In packaged desktop the
// IPC bridge owns navigation and its false/rejected result is final; launching
// a second renderer popup can duplicate a successful-but-ambiguously-reported
// OS open and is commonly blocked anyway. window.open is only for previews
// where the desktop bridge is genuinely absent.
async function openSignInUrl(url: string) {
  if (window.fabricDesktop?.openExternal) {
    try {
      const opened = await (window.fabricDesktop.openExternal as (target: string) => Promise<unknown>)(url)

      if (opened === false) {
        throw new Error('The sign-in page could not be opened.')
      }

      return
    } catch (error) {
      throw new Error(`The sign-in page could not be opened: ${errMessage(error)}`)
    }
  }

  const opened = window.open(url, '_blank', 'noopener,noreferrer')

  if (!opened) {
    throw new Error('The sign-in page was blocked. Allow pop-ups and try again.')
  }
}

export async function startProviderOAuth(
  provider: OAuthProvider,
  ctx: OnboardingContext,
  originatingProfile?: string | null
) {
  const profile = normalizeProfileKey(originatingProfile ?? $activeGatewayProfile.get())

  if (supportsAccountOwnershipChoice(provider.id)) {
    stopActiveSetupFlow()
    setFlow({ status: 'choosing_account', profile, provider })

    return
  }

  await beginProviderOAuth(provider, ctx, profile)
}

export async function continuePersonalProviderOAuth(ctx: OnboardingContext) {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'choosing_account' && flow.status !== 'managed_info') {
    return
  }

  await beginProviderOAuth(flow.provider, ctx, flow.profile)
}

export function showManagedProviderInfo() {
  const { flow } = $desktopOnboarding.get()

  if (flow.status === 'choosing_account') {
    managedRequestEpoch += 1
    setFlow({ status: 'managed_info', profile: flow.profile, provider: flow.provider, requesting: false })
  }
}

export async function requestManagedProviderAccess() {
  const initial = $desktopOnboarding.get().flow

  if (initial.status !== 'managed_info' || initial.requesting) {
    return
  }

  const { profile, provider } = initial
  const operationEpoch = ++managedRequestEpoch
  let requestCreated = false
  let launchAttempted = false

  const isCurrent = () => {
    const current = $desktopOnboarding.get().flow

    return (
      operationEpoch === managedRequestEpoch &&
      current.status === 'managed_info' &&
      current.profile === profile &&
      current.provider.id === provider.id
    )
  }

  setFlow({ ...initial, message: undefined, requesting: true })

  try {
    const current = await getProviderAccount(provider.id, profile)

    if (!isCurrent()) {
      return
    }

    const created = await createProviderManagedRequest(
      provider.id,
      'Fabric Desktop',
      current.snapshot.revision,
      profile
    )

    const request = created.request
    const handoff = created.snapshot.handoff

    requestCreated = created.created === true || request !== null

    if (
      !request ||
      !handoff ||
      handoff.channel !== 'email' ||
      handoff.delivery_verified !== false ||
      !handoff.uri.startsWith('mailto:')
    ) {
      throw new Error('Fabric returned an invalid managed-access handoff')
    }

    if (!isCurrent()) {
      return
    }

    // Calling the async opener invokes the desktop bridge synchronously up to
    // its first await, so this is the launch-attempt linearization point. Record
    // the server-owned `launch_attempted_unverified` transition exactly once
    // even if the OS later rejects the mailto open. The captured epoch prevents
    // an away-and-back operation from mutating the replacement flow.
    const launch = openSignInUrl(handoff.uri)

    launchAttempted = true

    if (isCurrent()) {
      void recordProviderAccountHandoff(provider.id, request.request_id, created.snapshot.revision, profile).catch(
        () => undefined
      )
    }

    await launch

    if (!isCurrent()) {
      return
    }

    const latest = $desktopOnboarding.get().flow

    if (isCurrent() && latest.status === 'managed_info') {
      setFlow({ ...latest, message: undefined, requesting: false })
    }
  } catch (error) {
    const latest = $desktopOnboarding.get().flow

    if (isCurrent() && latest.status === 'managed_info') {
      const message = launchAttempted
        ? `Request created, but the email app could not be opened: ${errMessage(error)}`
        : requestCreated
          ? `Request created, but the email handoff could not be prepared: ${errMessage(error)}`
          : `Could not create request: ${errMessage(error)}`

      setFlow({ ...latest, message, requesting: false })
    }
  }
}

export function showProviderAccountChoice() {
  const { flow } = $desktopOnboarding.get()

  if (flow.status === 'managed_info') {
    managedRequestEpoch += 1
    setFlow({ status: 'choosing_account', profile: flow.profile, provider: flow.provider })
  }
}

async function beginProviderOAuth(provider: OAuthProvider, ctx: OnboardingContext, profile: string, takeover = false) {
  stopActiveSetupFlow()
  const flowEpoch = oauthFlowEpoch

  if (provider.flow === 'external') {
    setFlow({
      status: 'external_pending',
      profile,
      provider: scopeExternalProviderCommand(provider, profile),
      copied: false
    })

    return
  }

  setFlow({ status: 'starting', profile, provider })

  let startedSession: OAuthStartResponse | undefined

  try {
    let expectedRevision: number | undefined

    if (supportsAccountOwnershipChoice(provider.id)) {
      const account = await getProviderAccount(provider.id, profile)

      if (flowEpoch !== oauthFlowEpoch) {
        return
      }

      expectedRevision = account.snapshot.revision
    }

    const start = await startOAuthLogin(provider.id, profile, {
      ...(expectedRevision === undefined ? {} : { expectedRevision }),
      ...(takeover ? { takeover: true } : {})
    })

    startedSession = start

    if (flowEpoch !== oauthFlowEpoch) {
      cancelSessionBestEffort(provider.id, start.session_id, profile)

      return
    }

    const browserUrl = start.flow === 'device_code' ? start.verification_url : start.auth_url
    await openSignInUrl(browserUrl)

    if (flowEpoch !== oauthFlowEpoch) {
      cancelSessionBestEffort(provider.id, start.session_id, profile)

      return
    }

    if (start.flow === 'pkce') {
      setFlow({ status: 'awaiting_user', profile, provider, start, code: '' })

      return
    }

    setFlow({ status: 'polling', profile, provider, start, copied: false })
    pollTimer = window.setInterval(() => void pollSession(provider, start, profile, ctx, flowEpoch), POLL_MS)
  } catch (error) {
    if (flowEpoch !== oauthFlowEpoch) {
      return
    }

    if (startedSession) {
      cancelSessionBestEffort(provider.id, startedSession.session_id, profile)
    }

    const conflict = errMessage(error).includes('oauth_in_progress')

    setFlow({
      status: 'error',
      profile,
      provider,
      message: conflict
        ? 'Another sign-in is already in progress for this account.'
        : `Could not start sign-in: ${errMessage(error)}`,
      takeoverAvailable: conflict
    })
  }
}

export async function takeoverProviderOAuth(ctx: OnboardingContext) {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'error' || !flow.takeoverAvailable || !flow.provider || !flow.profile) {
    return
  }

  await beginProviderOAuth(flow.provider, ctx, flow.profile, true)
}

// Poll a session-backed device-code flow until it resolves.
async function pollSession(
  provider: OAuthProvider,
  start: DeviceStart,
  profile: string,
  ctx: OnboardingContext,
  flowEpoch: number
) {
  if (flowEpoch !== oauthFlowEpoch || pollInFlightEpoch === flowEpoch) {
    return
  }

  pollInFlightEpoch = flowEpoch

  try {
    const { error_message, status } = await pollOAuthSession(provider.id, start.session_id, profile)

    if (flowEpoch !== oauthFlowEpoch) {
      return
    }

    if (status === 'approved') {
      clearPoll()
      setFlow({ status: 'success', profile, provider })
      await completeWithModelConfirm(
        ctx,
        provider.name,
        [provider.id],
        reason =>
          setFlow({
            status: 'error',
            profile,
            provider,
            message: providerResolutionFailure(reason)
          }),
        { oauthEpoch: flowEpoch, profile }
      )
    } else if (status !== 'pending') {
      clearPoll()
      setFlow({ status: 'error', profile, provider, start, message: error_message || `Sign-in ${status}.` })
    }
  } catch (error) {
    if (flowEpoch !== oauthFlowEpoch) {
      return
    }

    clearPoll()
    setFlow({ status: 'error', profile, provider, start, message: `Polling failed: ${errMessage(error)}` })
  } finally {
    if (pollInFlightEpoch === flowEpoch) {
      pollInFlightEpoch = null
    }
  }
}

export function setOnboardingCode(code: string) {
  const { flow } = $desktopOnboarding.get()

  if (flow.status === 'awaiting_user') {
    setFlow({ ...flow, code })
  }
}

export async function submitOnboardingCode(ctx: OnboardingContext) {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'awaiting_user' || !flow.code.trim()) {
    return
  }

  const { profile, provider, start, code } = flow
  const flowEpoch = oauthFlowEpoch
  setFlow({ status: 'submitting', profile, provider, start })

  try {
    const resp = await submitOAuthCode(provider.id, start.session_id, code.trim(), profile)

    if (flowEpoch !== oauthFlowEpoch) {
      return
    }

    if (resp.ok && resp.status === 'approved') {
      setFlow({ status: 'success', profile, provider })
      await completeWithModelConfirm(
        ctx,
        provider.name,
        [provider.id],
        reason =>
          setFlow({
            status: 'error',
            profile,
            provider,
            message: providerResolutionFailure(reason)
          }),
        { oauthEpoch: flowEpoch, profile }
      )
    } else {
      setFlow({ status: 'error', profile, provider, start, message: resp.message || 'Token exchange failed.' })
    }
  } catch (error) {
    if (flowEpoch !== oauthFlowEpoch) {
      return
    }

    setFlow({ status: 'error', profile, provider, start, message: errMessage(error) })
  }
}

export function cancelOnboardingFlow() {
  stopActiveSetupFlow()
  setFlow({ status: 'idle' })
}

async function copyAndFlash(text: string, predicate: (flow: OnboardingFlow) => boolean) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    return
  }

  const { flow } = $desktopOnboarding.get()

  if (!predicate(flow) || !('copied' in flow)) {
    return
  }

  setFlow({ ...flow, copied: true })
  window.setTimeout(() => {
    const current = $desktopOnboarding.get().flow

    if (predicate(current) && 'copied' in current) {
      setFlow({ ...current, copied: false })
    }
  }, COPY_FLASH_MS)
}

export async function copyDeviceCode() {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'polling') {
    return
  }

  const sid = flow.start.session_id
  await copyAndFlash(flow.start.user_code, f => f.status === 'polling' && f.start.session_id === sid)
}

export async function copyExternalCommand() {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'external_pending') {
    return
  }

  const id = flow.provider.id
  await copyAndFlash(flow.provider.cli_command, f => f.status === 'external_pending' && f.provider.id === id)
}

export async function recheckExternalSignin(ctx: OnboardingContext) {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'external_pending') {
    return
  }

  const { profile, provider } = flow
  const flowEpoch = oauthFlowEpoch
  await completeWithModelConfirm(
    ctx,
    provider.name,
    [provider.id],
    reason =>
      setFlow({
        status: 'error',
        profile,
        provider,
        message:
          reason?.trim() ||
          brandText(`Fabric still cannot reach ${provider.name}. Run \`${provider.cli_command}\` in a terminal first.`)
      }),
    { oauthEpoch: flowEpoch, profile }
  )
}

export async function saveOnboardingApiKey(
  envKey: string,
  value: string,
  label: string,
  ctx: OnboardingContext,
  // Optional endpoint key — only meaningful for the "Local / custom endpoint"
  // option, whose primary `value` is the base URL. Ignored for plain API-key
  // providers (their key IS `value`).
  endpointApiKey?: string
) {
  const trimmed = value.trim()

  if (!trimmed) {
    return { ok: false, message: 'Enter a value first.' }
  }

  // The "Local / custom endpoint" option carries a base URL (in `value`) plus
  // an optional API key. It must be wired into config (provider=custom +
  // base_url + model + api_key), not dropped into .env — runtime resolution
  // ignores OPENAI_BASE_URL.
  if (envKey === 'OPENAI_BASE_URL') {
    return saveOnboardingLocalEndpoint(trimmed, endpointApiKey?.trim() ?? '', ctx)
  }

  if (envKey === 'native:ollama') {
    return saveOnboardingNativeOllama(trimmed, ctx)
  }

  stopActiveSetupFlow()
  const flowEpoch = oauthFlowEpoch
  const profile = normalizeProfileKey($activeGatewayProfile.get())
  const cancelled = () => ({ ok: false, message: 'Provider setup was cancelled.' })

  // No key validation here on purpose: we previously live-probed the key and
  // hard-blocked on a runtime check after saving, which rejected too many
  // legitimate users (corporate proxies, regional blocks, flaky/rate-limited
  // provider probes, self-hosted endpoints). We now save the value as-is and
  // let the user proceed; an actually-bad key surfaces later at chat time.
  try {
    await setEnvVar(envKey, trimmed, profile)

    if (flowEpoch !== oauthFlowEpoch) {
      return cancelled()
    }

    // For API-key flows we don't have a definitive provider id (the
    // user picked which API key they're entering, but the corresponding
    // backend slug — e.g. OPENROUTER_API_KEY → "openrouter" — is the
    // env-key prefix stripped). Pass a couple of likely candidates;
    // fetchProviderDefaultModel falls back to the first authenticated
    // provider returned by /api/model/options if none match.
    const slugCandidates = [envKey.replace(/_API_KEY$/, '').toLowerCase(), label.toLowerCase()]
    // ignoreRuntimeGate=true: never block onboarding on the runtime check.
    await completeWithModelConfirm(ctx, label, slugCandidates, () => undefined, {
      ignoreRuntimeGate: true,
      oauthEpoch: flowEpoch,
      profile
    })

    if (flowEpoch !== oauthFlowEpoch) {
      return cancelled()
    }

    return { ok: true }
  } catch (error) {
    if (flowEpoch !== oauthFlowEpoch) {
      return cancelled()
    }

    notifyError(error, `Could not save ${label}`)

    return { ok: false, message: errMessage(error) }
  }
}

// Configure a local / self-hosted OpenAI-compatible endpoint (vLLM, llama.cpp,
// Ollama, …). Unlike API-key providers, a local endpoint is defined by its URL
// and usually needs NO key. The runtime resolver reads model.base_url from
// config (it ignores the OPENAI_BASE_URL env var), so we persist
// provider=custom + base_url + model via /api/model/set rather than dropping an
// env var that resolution never consults.
//
// Models are discovered from the endpoint's /v1/models (surfaced by the
// validate probe). A single unique model keeps the zero-friction fast path. If
// several models are available, we hold the URL and optional key in renderer
// memory and require an explicit choice before persisting anything. We cannot
// reuse completeWithModelConfirm: that generic path writes an assignment
// without base_url/api_key and would disconnect the custom endpoint.
export async function saveOnboardingLocalEndpoint(baseUrl: string, apiKey: string, ctx: OnboardingContext) {
  const url = baseUrl.trim()
  const key = apiKey.trim()

  if (!url) {
    return { ok: false, message: 'Enter the endpoint URL first.' }
  }

  stopActiveSetupFlow()
  const flowEpoch = localEndpointFlowEpoch
  const profile = normalizeProfileKey($activeGatewayProfile.get())

  // Probe OpenAI compatibility + discover the served models. An HTTP error
  // proves only that the host is reachable; setup proceeds only when the
  // endpoint returns a recognizable model catalog.
  let models: string[] = []

  try {
    const probe = await validateProviderCredential('OPENAI_BASE_URL', url, key, profile)

    if (flowEpoch !== localEndpointFlowEpoch) {
      return { ok: false, message: 'Local endpoint setup was cancelled.' }
    }

    if (!probe.ok && probe.reachable) {
      return { ok: false, message: probe.message || 'Could not reach that endpoint.' }
    }

    if (!probe.reachable) {
      return { ok: false, message: probe.message || `Could not reach ${url}.` }
    }

    models = [...new Set((probe.models ?? []).map(model => String(model).trim()).filter(Boolean))]
  } catch {
    if (flowEpoch !== localEndpointFlowEpoch) {
      return { ok: false, message: 'Local endpoint setup was cancelled.' }
    }

    return { ok: false, message: `Could not reach ${url}.` }
  }

  if (models.length === 0) {
    return {
      ok: false,
      message: `Connected to ${url}, but it advertised no models at /v1/models. Start a model on that endpoint and try again.`
    }
  }

  if (models.length > 1) {
    setFlow({
      status: 'confirming_local_model',
      apiKey: key,
      baseUrl: url,
      currentModel: '',
      localProvider: 'custom',
      models,
      profile,
      saving: false
    })

    return { ok: true }
  }

  return persistOnboardingLocalEndpoint(url, key, models[0], profile, ctx, flowEpoch, 'custom')
}

export async function saveOnboardingNativeOllama(baseUrl: string, ctx: OnboardingContext) {
  const url = baseUrl.trim()

  if (!url) {
    return { ok: false, message: 'Enter the Ollama server URL first.' }
  }

  stopActiveSetupFlow()
  const flowEpoch = localEndpointFlowEpoch
  const profile = normalizeProfileKey($activeGatewayProfile.get())

  try {
    const discovery = await discoverLocalOllama(url, profile)

    if (flowEpoch !== localEndpointFlowEpoch) {
      return { ok: false, message: 'Ollama setup was cancelled.' }
    }

    if (discovery.state !== 'reachable') {
      return { ok: false, message: 'Could not reach a native Ollama model catalog at that address.' }
    }

    const models = [...new Set(discovery.models.map(model => String(model).trim()).filter(Boolean))]

    if (models.length === 0) {
      return {
        ok: false,
        message: 'Ollama is reachable but has no installed models. Run `fabric ollama pull MODEL` and try again.'
      }
    }

    if (models.length > 1) {
      setFlow({
        status: 'confirming_local_model',
        apiKey: '',
        baseUrl: discovery.base_url,
        currentModel: '',
        localProvider: 'ollama',
        models,
        profile,
        saving: false
      })

      return { ok: true }
    }

    return persistOnboardingLocalEndpoint(discovery.base_url, '', models[0], profile, ctx, flowEpoch, 'ollama')
  } catch (error) {
    if (flowEpoch !== localEndpointFlowEpoch) {
      return { ok: false, message: 'Ollama setup was cancelled.' }
    }

    return { ok: false, message: errMessage(error) }
  }
}

async function persistOnboardingLocalEndpoint(
  url: string,
  key: string,
  model: string,
  profile: string,
  ctx: OnboardingContext,
  flowEpoch: number,
  localProvider: 'custom' | 'ollama'
) {
  if (flowEpoch !== localEndpointFlowEpoch) {
    return { ok: false, message: 'Local endpoint setup was cancelled.' }
  }

  try {
    if (localProvider === 'ollama') {
      await configureLocalOllama(url, model, profile)
    } else {
      await setModelAssignment({ scope: 'main', provider: 'custom', model, base_url: url, api_key: key }, profile)
    }

    if (flowEpoch !== localEndpointFlowEpoch) {
      return { ok: false, message: 'Local endpoint setup was cancelled.' }
    }

    await ctx.requestGateway('reload.env', { profile }).catch(() => undefined)

    if (flowEpoch !== localEndpointFlowEpoch) {
      return { ok: false, message: 'Local endpoint setup was cancelled.' }
    }

    const runtime = await checkRuntime(ctx, undefined, profile)

    if (flowEpoch !== localEndpointFlowEpoch) {
      return { ok: false, message: 'Local endpoint setup was cancelled.' }
    }

    if (!runtime.ready) {
      const detail = (runtime.reason ?? '').trim()

      return { ok: false, message: detail || brandText(`Saved, but Fabric still cannot reach ${url}.`) }
    }

    if (completeDesktopOnboarding(profile)) {
      notifyReady(localProvider === 'ollama' ? 'Ollama (local)' : 'Local / custom endpoint')
      ctx.onCompleted?.()
    }

    return { ok: true }
  } catch (error) {
    notifyError(error, 'Could not save local endpoint')

    return { ok: false, message: errMessage(error) }
  }
}

export function setOnboardingLocalModel(model: string) {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'confirming_local_model' || flow.saving || !flow.models.includes(model)) {
    return
  }

  setFlow({ ...flow, currentModel: model, message: undefined })
}

export async function confirmOnboardingLocalModel(ctx: OnboardingContext) {
  const { flow } = $desktopOnboarding.get()

  if (
    flow.status !== 'confirming_local_model' ||
    flow.saving ||
    !flow.currentModel ||
    !flow.models.includes(flow.currentModel)
  ) {
    return { ok: false, message: 'Choose a model first.' }
  }

  const flowEpoch = localEndpointFlowEpoch
  setFlow({ ...flow, saving: true, message: undefined })

  const result = await persistOnboardingLocalEndpoint(
    flow.baseUrl,
    flow.apiKey,
    flow.currentModel,
    flow.profile,
    ctx,
    flowEpoch,
    flow.localProvider
  )

  if (!result.ok && flowEpoch === localEndpointFlowEpoch) {
    const current = $desktopOnboarding.get().flow

    if (current.status === 'confirming_local_model') {
      setFlow({ ...current, saving: false, message: result.message })
    }
  }

  return result
}

// User picked a different model from the dropdown on the confirm card.
// Persists immediately so the displayed value is always what's on disk.
export async function setOnboardingModel(model: string, providerSlug?: string) {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'confirming_model' || flow.saving) {
    return
  }

  const nextModel = model.trim()
  const nextProvider = providerSlug?.trim() || flow.providerSlug

  if (!nextModel || !nextProvider) {
    return
  }

  // Optimistic update so the dropdown feels instant; revert on failure.
  const previousModel = flow.currentModel
  const previousProvider = flow.providerSlug
  const flowEpoch = oauthFlowEpoch
  setFlow({ ...flow, currentModel: nextModel, providerSlug: nextProvider, saving: true })

  const currentConfirmation = () => {
    const current = $desktopOnboarding.get().flow

    return flowEpoch === oauthFlowEpoch &&
      current.status === 'confirming_model' &&
      current.profile === flow.profile &&
      current.label === flow.label &&
      current.providerSlug === nextProvider
      ? current
      : null
  }

  try {
    await setModelAssignment(
      {
        scope: 'main',
        provider: nextProvider,
        model: nextModel
      },
      flow.profile
    )
    const current = currentConfirmation()

    if (current) {
      setFlow({ ...current, currentModel: nextModel, saving: false })
    }
  } catch (error) {
    const current = currentConfirmation()

    if (current) {
      notifyError(error, 'Could not change model')
      setFlow({ ...current, currentModel: previousModel, providerSlug: previousProvider, saving: false })
    }
  }
}

// User clicked "Start chatting" on the confirm card. Finalizes onboarding
// — the model was already persisted by completeWithModelConfirm (or by
// setOnboardingModel if they changed it), so all that's left is to mark
// onboarding done and unblock the rest of the app.
export function confirmOnboardingModel(ctx: OnboardingContext) {
  const { flow } = $desktopOnboarding.get()

  if (flow.status !== 'confirming_model') {
    return
  }

  // No success toast here: the confirm-model screen already showed "<provider>
  // connected." notifyReady is reserved for completion paths that SKIP this
  // screen (no-default fallthrough, local endpoint) so feedback isn't lost.
  if (completeDesktopOnboarding(flow.profile)) {
    ctx.onCompleted?.()
  }
}
