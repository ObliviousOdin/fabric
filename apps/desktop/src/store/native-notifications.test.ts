import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/approval-sound', () => ({
  playApprovalSound: vi.fn(),
  previewApprovalSound: vi.fn()
}))

import { playApprovalSound } from '@/lib/approval-sound'

import { $gateway } from './gateway'
import {
  dispatchNativeNotification,
  maybePlayApprovalSound,
  NATIVE_NOTIFICATION_KINDS,
  resetApprovalSoundThrottle,
  respondToApprovalAction,
  sendTestNativeNotification,
  setNativeNotifyEnabled,
  setNativeNotifyKind
} from './native-notifications'
import { $approvalRequest, clearAllPrompts, setApprovalRequest } from './prompts'
import { $activeSessionId, setActiveSessionId } from './session'

const desktopWindow = window as unknown as { fabricDesktop?: Window['fabricDesktop'] }
const initialFabricDesktop = desktopWindow.fabricDesktop

const notify = vi.fn().mockResolvedValue(true)

function setWindowState({ focused = true, hidden = false }: { focused?: boolean; hidden?: boolean }) {
  Object.defineProperty(document, 'hidden', { configurable: true, value: hidden })
  Object.defineProperty(document, 'hasFocus', { configurable: true, value: () => focused })
}

let counter = 0

// Unique session id per call dodges the per-(kind,session) throttle so each
// assertion starts clean.
function freshSession(): string {
  counter += 1

  return `session-${counter}`
}

beforeEach(() => {
  notify.mockClear()
  desktopWindow.fabricDesktop = { notify } as unknown as Window['fabricDesktop']
  setNativeNotifyEnabled(true)

  for (const kind of NATIVE_NOTIFICATION_KINDS) {
    setNativeNotifyKind(kind, true)
  }

  setActiveSessionId(null)
  setWindowState({ focused: false, hidden: true })
})

afterEach(() => {
  clearAllPrompts()

  if (initialFabricDesktop) {
    desktopWindow.fabricDesktop = initialFabricDesktop
  } else {
    delete desktopWindow.fabricDesktop
  }
})

describe('dispatchNativeNotification focus gating', () => {
  it('fires a completion notification for the active session when the window is hidden', () => {
    const sessionId = freshSession()
    setActiveSessionId(sessionId)
    dispatchNativeNotification({ kind: 'turnDone', sessionId, title: 'done' })
    expect(notify).toHaveBeenCalledTimes(1)
  })

  it('fires a completion notification when the window is visible but unfocused (alt-tab)', () => {
    const sessionId = freshSession()
    setActiveSessionId(sessionId)
    setWindowState({ focused: false, hidden: false })
    dispatchNativeNotification({ kind: 'turnDone', sessionId, title: 'done' })
    expect(notify).toHaveBeenCalledTimes(1)
  })

  it('suppresses a completion notification when the window is focused', () => {
    const sessionId = freshSession()
    setActiveSessionId(sessionId)
    setWindowState({ focused: true, hidden: false })
    dispatchNativeNotification({ kind: 'turnDone', sessionId, title: 'done' })
    expect(notify).not.toHaveBeenCalled()
  })

  it('suppresses a completion notification for a non-active background session (no gateway spam)', () => {
    setActiveSessionId('on-screen')
    dispatchNativeNotification({ kind: 'turnDone', sessionId: 'busy-bot-session', title: 'done' })
    expect(notify).not.toHaveBeenCalled()
  })

  it('fires an attention notification for an off-screen session even when focused', () => {
    setWindowState({ focused: true, hidden: false })
    setActiveSessionId('on-screen')
    dispatchNativeNotification({ kind: 'approval', sessionId: 'background', title: 'approve' })
    expect(notify).toHaveBeenCalledTimes(1)
  })

  it('suppresses an attention notification for the active session when focused', () => {
    setWindowState({ focused: true, hidden: false })
    setActiveSessionId('on-screen')
    dispatchNativeNotification({ kind: 'approval', sessionId: 'on-screen', title: 'approve' })
    expect(notify).not.toHaveBeenCalled()
  })

  it('fires a global completion notification while away with no active session (pet gen)', () => {
    setActiveSessionId(null)
    dispatchNativeNotification({ global: true, kind: 'backgroundDone', title: 'Your pet hatched' })
    expect(notify).toHaveBeenCalledTimes(1)
  })

  it('suppresses a global notification when the window is focused', () => {
    setWindowState({ focused: true, hidden: false })
    setActiveSessionId(null)
    dispatchNativeNotification({ global: true, kind: 'backgroundDone', title: 'Your pet hatched' })
    expect(notify).not.toHaveBeenCalled()
  })
})

describe('dispatchNativeNotification preferences', () => {
  it('suppresses everything when the master switch is off', () => {
    setNativeNotifyEnabled(false)
    dispatchNativeNotification({ kind: 'approval', sessionId: freshSession(), title: 'approve' })
    dispatchNativeNotification({ kind: 'turnDone', sessionId: freshSession(), title: 'done' })
    expect(notify).not.toHaveBeenCalled()
  })

  it('suppresses only the disabled kind', () => {
    const sessionId = freshSession()
    setActiveSessionId(sessionId)
    setNativeNotifyKind('turnDone', false)
    dispatchNativeNotification({ kind: 'turnDone', sessionId, title: 'done' })
    expect(notify).not.toHaveBeenCalled()

    dispatchNativeNotification({ kind: 'turnError', sessionId, title: 'boom' })
    expect(notify).toHaveBeenCalledTimes(1)
  })

  it('forwards kind, requestId, and sessionId to the bridge', () => {
    setActiveSessionId('abc')
    dispatchNativeNotification({
      body: 'hi',
      kind: 'turnError',
      requestId: 'approval-1',
      sessionId: 'abc',
      title: 'boom'
    })
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        body: 'hi',
        kind: 'turnError',
        requestId: 'approval-1',
        sessionId: 'abc',
        title: 'boom'
      })
    )
  })
})

describe('dispatchNativeNotification throttle', () => {
  it('collapses duplicate kind+session within the throttle window', () => {
    const sessionId = freshSession()
    setActiveSessionId(sessionId)
    dispatchNativeNotification({ kind: 'turnDone', sessionId, title: 'done' })
    dispatchNativeNotification({ kind: 'turnDone', sessionId, title: 'done again' })
    expect(notify).toHaveBeenCalledTimes(1)
  })
})

describe('sendTestNativeNotification', () => {
  it('fires regardless of focus or active session', () => {
    setWindowState({ focused: true, hidden: false })
    setActiveSessionId('on-screen')
    sendTestNativeNotification('Fabric', 'works')
    expect(notify).toHaveBeenCalledTimes(1)
  })
})

describe('$activeSessionId wiring', () => {
  it('reflects the setter used for gating', () => {
    setActiveSessionId('xyz')
    expect($activeSessionId.get()).toBe('xyz')
  })
})

describe('respondToApprovalAction', () => {
  const request = vi.fn().mockResolvedValue({ request_id: 'approval-1', resolved: 1 })

  beforeEach(() => {
    request.mockClear()
    $gateway.set({ request } as unknown as ReturnType<typeof $gateway.get>)
  })

  afterEach(() => {
    $gateway.set(null)
  })

  it('approves via approval.respond {choice: "once"} and clears the prompt', async () => {
    setActiveSessionId('bg')
    setApprovalRequest({ command: 'rm -rf /', description: 'dangerous', requestId: 'approval-1', sessionId: 'bg' })

    await respondToApprovalAction('bg', 'approval-1', 'approve')

    expect(request).toHaveBeenCalledWith('approval.respond', {
      choice: 'once',
      request_id: 'approval-1',
      session_id: 'bg'
    })
    expect($approvalRequest.get()).toBeNull()
  })

  it('rejects via approval.respond {choice: "deny"}', async () => {
    await respondToApprovalAction('bg', 'approval-1', 'reject')
    expect(request).toHaveBeenCalledWith('approval.respond', {
      choice: 'deny',
      request_id: 'approval-1',
      session_id: 'bg'
    })
  })

  it('allows only one in-flight response for the same approval identity', async () => {
    let resolveRequest: ((value: { request_id: string; resolved: number }) => void) | undefined
    request.mockImplementationOnce(
      () =>
        new Promise<{ request_id: string; resolved: number }>(resolve => {
          resolveRequest = resolve
        })
    )

    const approve = respondToApprovalAction('bg', 'approval-1', 'approve')
    const reject = respondToApprovalAction('bg', 'approval-1', 'reject')

    expect(request).toHaveBeenCalledTimes(1)
    resolveRequest?.({ request_id: 'approval-1', resolved: 1 })
    await Promise.all([approve, reject])
  })

  it('ignores unknown action ids', async () => {
    await respondToApprovalAction('bg', 'approval-1', 'snooze')
    expect(request).not.toHaveBeenCalled()
  })

  it('does not act without an authoritative request id', async () => {
    await respondToApprovalAction('bg', undefined, 'approve')
    expect(request).not.toHaveBeenCalled()
  })

  it('keeps the prompt when the backend resolves zero approvals', async () => {
    setActiveSessionId('bg')
    setApprovalRequest({ command: 'rm -rf /', description: 'dangerous', requestId: 'approval-1', sessionId: 'bg' })
    request.mockResolvedValueOnce({ resolved: 0 })

    await respondToApprovalAction('bg', 'approval-1', 'approve')

    expect($approvalRequest.get()?.requestId).toBe('approval-1')
  })

  it('does not clear a newer prompt after an old notification resolves', async () => {
    setActiveSessionId('bg')
    setApprovalRequest({ command: 'new command', description: 'dangerous', requestId: 'approval-2', sessionId: 'bg' })

    await respondToApprovalAction('bg', 'approval-1', 'approve')

    expect($approvalRequest.get()?.requestId).toBe('approval-2')
  })

  it('no-ops without a gateway', async () => {
    $gateway.set(null)
    await respondToApprovalAction('bg', 'approval-1', 'approve')
    expect(request).not.toHaveBeenCalled()
  })
})

describe('maybePlayApprovalSound', () => {
  const playSound = vi.mocked(playApprovalSound)

  beforeEach(() => {
    playSound.mockClear()
    resetApprovalSoundThrottle()
    // Focused + visible → shouldFire suppresses the native banner, so the in-app
    // cue is the only alert. This is exactly the gap #50 fills.
    setWindowState({ focused: true, hidden: false })
    setActiveSessionId('sess-1')
  })

  it('plays for a blocking approval on the focused active session', () => {
    maybePlayApprovalSound('sess-1', 'rm -rf /tmp/x')
    expect(playSound).toHaveBeenCalledTimes(1)
  })

  it('does not replay the same session+command (reconnect replay)', () => {
    maybePlayApprovalSound('sess-1', 'rm -rf /tmp/x')
    maybePlayApprovalSound('sess-1', 'rm -rf /tmp/x')
    expect(playSound).toHaveBeenCalledTimes(1)
  })

  it('plays again for a different command in the same session', () => {
    maybePlayApprovalSound('sess-1', 'rm -rf /tmp/x')
    maybePlayApprovalSound('sess-1', 'chmod -R 777 /tmp/y')
    expect(playSound).toHaveBeenCalledTimes(2)
  })

  it('stays silent for an off-screen (non-active) session', () => {
    maybePlayApprovalSound('sess-2', 'rm -rf /tmp/x')
    expect(playSound).not.toHaveBeenCalled()
  })

  it('stays silent with no session id', () => {
    maybePlayApprovalSound(null, 'rm -rf /tmp/x')
    expect(playSound).not.toHaveBeenCalled()
  })

  it('stays silent when backgrounded — the native notification already sounds', () => {
    setWindowState({ focused: false, hidden: false })
    maybePlayApprovalSound('sess-1', 'rm -rf /tmp/x')
    expect(playSound).not.toHaveBeenCalled()
  })

  it('plays again once the throttle is reset', () => {
    maybePlayApprovalSound('sess-1', 'rm -rf /tmp/x')
    resetApprovalSoundThrottle()
    maybePlayApprovalSound('sess-1', 'rm -rf /tmp/x')
    expect(playSound).toHaveBeenCalledTimes(2)
  })
})
