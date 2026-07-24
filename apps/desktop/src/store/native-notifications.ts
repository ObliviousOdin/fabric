import { atom } from 'nanostores'

import { playApprovalSound } from '@/lib/approval-sound'
import {
  type ApprovalResolutionResponse,
  approvalResponseResolved,
  ownedPromptResponseParams
} from '@/lib/prompt-responses'
import { persistString, storedString } from '@/lib/storage'

import { $gateway } from './gateway'
import { clearApprovalRequest } from './prompts'
import { $activeSessionId } from './session'

// Native OS notifications (Electron `Notification`), separate from the in-app
// toast feed in `notifications.ts`. Each kind toggles independently.
export type NativeNotificationKind = 'approval' | 'backgroundDone' | 'input' | 'turnDone' | 'turnError'

export const NATIVE_NOTIFICATION_KINDS: readonly NativeNotificationKind[] = [
  'approval',
  'input',
  'turnDone',
  'turnError',
  'backgroundDone'
]

// Blocking prompts — surface even while focused if they're for another session.
const ATTENTION_KINDS = new Set<NativeNotificationKind>(['approval', 'input'])

export interface NativeNotificationPrefs {
  enabled: boolean
  kinds: Record<NativeNotificationKind, boolean>
}

const STORAGE_KEY = 'fabric:native-notifications'

const DEFAULT_PREFS: NativeNotificationPrefs = {
  enabled: true,
  kinds: { approval: true, backgroundDone: true, input: true, turnDone: true, turnError: true }
}

function readPrefs(): NativeNotificationPrefs {
  const raw = storedString(STORAGE_KEY)

  if (!raw) {
    return DEFAULT_PREFS
  }

  try {
    const parsed = JSON.parse(raw) as Partial<NativeNotificationPrefs>
    const kinds = { ...DEFAULT_PREFS.kinds }

    for (const kind of NATIVE_NOTIFICATION_KINDS) {
      const value = parsed.kinds?.[kind]

      if (typeof value === 'boolean') {
        kinds[kind] = value
      }
    }

    return {
      enabled: typeof parsed.enabled === 'boolean' ? parsed.enabled : DEFAULT_PREFS.enabled,
      kinds
    }
  } catch {
    return DEFAULT_PREFS
  }
}

export const $nativeNotifyPrefs = atom<NativeNotificationPrefs>(readPrefs())

function writePrefs(next: NativeNotificationPrefs) {
  $nativeNotifyPrefs.set(next)
  persistString(STORAGE_KEY, JSON.stringify(next))
}

export function setNativeNotifyEnabled(enabled: boolean) {
  writePrefs({ ...$nativeNotifyPrefs.get(), enabled })
}

export function setNativeNotifyKind(kind: NativeNotificationKind, on: boolean) {
  const prev = $nativeNotifyPrefs.get()
  writePrefs({ ...prev, kinds: { ...prev.kinds, [kind]: on } })
}

// De-dupe replayed events for the same kind+session. Self-evicting: entries
// older than the window are pruned on every dispatch, so the map can't grow.
const THROTTLE_MS = 1000
const lastFiredAt = new Map<string, number>()

function throttled(key: string, now: number): boolean {
  for (const [k, at] of lastFiredAt) {
    if (now - at >= THROTTLE_MS) {
      lastFiredAt.delete(k)
    }
  }

  if (lastFiredAt.has(key)) {
    return true
  }

  lastFiredAt.set(key, now)

  return false
}

// "Backgrounded" = the user isn't on Fabric. `document.hidden` only flips when
// minimized/occluded; an alt-tabbed window is visible-but-unfocused, so we also
// check `document.hasFocus()`.
function isBackgrounded(): boolean {
  if (typeof document === 'undefined') {
    return false
  }

  if (document.hidden) {
    return true
  }

  return typeof document.hasFocus === 'function' && !document.hasFocus()
}

function shouldFire(kind: NativeNotificationKind, sessionId?: null | string, global = false): boolean {
  // Global notifications aren't tied to a chat session (e.g. pet generation,
  // which runs from the command center with no active conversation). They fire
  // whenever the user is away, with no session-match requirement — otherwise a
  // background run started without an open session would be silently dropped.
  if (global) {
    return isBackgrounded()
  }

  // Attention kinds break through for an off-screen session even while focused.
  if (ATTENTION_KINDS.has(kind)) {
    return isBackgrounded() || (Boolean(sessionId) && sessionId !== $activeSessionId.get())
  }

  // Completion kinds: only the active session, only while away — so a busy
  // gateway (messaging, kanban, cron) can't spam a toast per background session.
  return isBackgrounded() && Boolean(sessionId) && sessionId === $activeSessionId.get()
}

export interface NativeNotificationAction {
  id: string
  text: string
}

export interface NativeNotificationInput {
  kind: NativeNotificationKind
  title: string
  body?: string
  sessionId?: null | string
  requestId?: string
  /**
   * Not tied to a chat session (e.g. pet generation). Fires whenever the user
   * is away, bypassing the session-match gate that completion kinds normally
   * require.
   */
  global?: boolean
  silent?: boolean
  actions?: NativeNotificationAction[]
}

export function dispatchNativeNotification(input: NativeNotificationInput): void {
  const prefs = $nativeNotifyPrefs.get()

  if (!prefs.enabled || !prefs.kinds[input.kind]) {
    return
  }

  if (!shouldFire(input.kind, input.sessionId, input.global)) {
    return
  }

  if (throttled(`${input.kind}:${input.sessionId ?? (input.global ? 'global' : '')}`, Date.now())) {
    return
  }

  void window.fabricDesktop?.notify({
    actions: input.actions,
    body: input.body,
    kind: input.kind,
    requestId: input.requestId,
    sessionId: input.sessionId ?? undefined,
    silent: input.silent,
    title: input.title
  })
}

// Approval cue de-dupe: a re-raised/replayed approval.request for the same
// session+command (e.g. on gateway reconnect) must not replay the sound.
// Self-evicting on a short window, like the native-notification throttle above.
const APPROVAL_SOUND_WINDOW_MS = 2000
const approvalSoundFiredAt = new Map<string, number>()

// Test seam: clear the de-dupe ledger between cases.
export function resetApprovalSoundThrottle(): void {
  approvalSoundFiredAt.clear()
}

// Play the in-app approval cue when a blocking approval lands on the *focused*
// active session — the one case shouldFire() suppresses the native OS
// notification (it's neither backgrounded nor an off-screen session), so without
// a sound a user who stepped away while Fabric stayed focused can miss it. For a
// backgrounded app or an off-screen session the native notification already
// carries its own sound, so staying silent here avoids doubling up.
export function maybePlayApprovalSound(sessionId?: null | string, command?: string): void {
  if (isBackgrounded() || !sessionId || sessionId !== $activeSessionId.get()) {
    return
  }

  const now = Date.now()

  for (const [key, at] of approvalSoundFiredAt) {
    if (now - at >= APPROVAL_SOUND_WINDOW_MS) {
      approvalSoundFiredAt.delete(key)
    }
  }

  const dedupeKey = `${sessionId} ${command ?? ''}`

  if (approvalSoundFiredAt.has(dedupeKey)) {
    return
  }

  approvalSoundFiredAt.set(dedupeKey, now)
  playApprovalSound()
}

// Resolve a pending approval from a notification button, mirroring the in-app
// Run/Reject bar. The notification round-trip carries the exact request id so
// an old OS button cannot resolve or dismiss a newer approval in that session.
const approvalResponsesInFlight = new Set<string>()

export async function respondToApprovalAction(
  sessionId: null | string,
  requestId: string | undefined,
  actionId: string
): Promise<void> {
  const choice = actionId === 'approve' ? 'once' : actionId === 'reject' ? 'deny' : null

  if (!choice || !requestId) {
    return
  }

  const responseKey = `${sessionId ?? ''}\u0000${requestId}`

  if (approvalResponsesInFlight.has(responseKey)) {
    return
  }

  const gateway = $gateway.get()

  if (!gateway) {
    return
  }

  approvalResponsesInFlight.add(responseKey)

  try {
    const response = await gateway.request<ApprovalResolutionResponse>(
      'approval.respond',
      ownedPromptResponseParams({ requestId, sessionId }, { choice })
    )

    if (approvalResponseResolved(response, requestId)) {
      clearApprovalRequest(sessionId, requestId)
    }
  } catch {
    // Leave the prompt parked so the user can still resolve it in-app.
  } finally {
    approvalResponsesInFlight.delete(responseKey)
  }
}

// Settings "send test" — bypasses gating. Returns whether the OS accepted it so
// the panel can flag a silent permission failure instead of looking dead.
export async function sendTestNativeNotification(title: string, body: string): Promise<boolean> {
  const bridge = window.fabricDesktop

  if (!bridge?.notify) {
    return false
  }

  try {
    return await bridge.notify({ body, kind: 'turnDone', title })
  } catch {
    return false
  }
}
