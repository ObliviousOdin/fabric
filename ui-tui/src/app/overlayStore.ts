import { atom, computed } from 'nanostores'

import type { ApprovalReq } from '../types.js'

import type { OverlayState } from './interfaces.js'

// Parallel tool calls can block on more than one approval in a single
// session. The overlay renders one prompt at a time, so preserve the remaining
// requests here in gateway-arrival order instead of letting a later event
// overwrite the visible request.
let approvalBacklog: ApprovalReq[] = []

const buildOverlayState = (): OverlayState => ({
  agents: false,
  agentsInitialHistoryIndex: 0,
  approval: null,
  billing: null,
  clarify: null,
  confirm: null,
  journey: false,
  modelPicker: false,
  pager: null,
  petPicker: false,
  pluginsHub: false,
  secret: null,
  sessions: false,
  skillsHub: false,
  sudo: null
})

export const $overlayState = atom<OverlayState>(buildOverlayState())

export const $isBlocked = computed(
  $overlayState,
  ({
    agents,
    approval,
    billing,
    clarify,
    confirm,
    journey,
    modelPicker,
    pager,
    petPicker,
    pluginsHub,
    secret,
    sessions,
    skillsHub,
    sudo
  }) =>
    Boolean(
      agents ||
      approval ||
      billing ||
      clarify ||
      confirm ||
      journey ||
      modelPicker ||
      pager ||
      petPicker ||
      pluginsHub ||
      secret ||
      sessions ||
      skillsHub ||
      sudo
    )
)

export const getOverlayState = () => $overlayState.get()

export const patchOverlayState = (next: Partial<OverlayState> | ((state: OverlayState) => OverlayState)) =>
  $overlayState.set(typeof next === 'function' ? next($overlayState.get()) : { ...$overlayState.get(), ...next })

/** Full reset — used by session/turn teardown and tests. */
export const resetOverlayState = () => {
  approvalBacklog = []
  $overlayState.set(buildOverlayState())
}

export const enqueueApproval = (request: ApprovalReq) => {
  const state = $overlayState.get()

  if (!state.approval) {
    patchOverlayState({ approval: request })

    return
  }

  if (state.approval.requestId === request.requestId) {
    patchOverlayState({ approval: request })

    return
  }

  const existingIndex = approvalBacklog.findIndex(item => item.requestId === request.requestId)

  if (existingIndex >= 0) {
    approvalBacklog = approvalBacklog.map((item, index) => (index === existingIndex ? request : item))
  } else {
    approvalBacklog = [...approvalBacklog, request]
  }
}

/**
 * Remove one backend-confirmed approval by its authoritative id. Resolving the
 * visible head immediately promotes its next sibling; a stale id is a no-op.
 */
export const completeApproval = (requestId: string): boolean => {
  const state = $overlayState.get()

  if (state.approval?.requestId === requestId) {
    const [next = null, ...remaining] = approvalBacklog
    approvalBacklog = remaining
    patchOverlayState({ approval: next })

    return true
  }

  const nextBacklog = approvalBacklog.filter(request => request.requestId !== requestId)

  if (nextBacklog.length === approvalBacklog.length) {
    return false
  }

  approvalBacklog = nextBacklog

  return true
}

/**
 * Soft reset: drop FLOW-scoped overlays (approval / clarify / confirm / sudo
 * / secret / pager) but PRESERVE user-toggled ones — agents dashboard, model
 * picker, skills hub, sessions overlay.  Those are opened deliberately and
 * shouldn't vanish when a turn ends.  Called from turnController.idle() on
 * every turn completion / interrupt; the old "reset everything" behaviour
 * silently closed /agents the moment delegation finished.
 */
export const resetFlowOverlays = () => {
  approvalBacklog = []
  $overlayState.set({
    ...buildOverlayState(),
    agents: $overlayState.get().agents,
    agentsInitialHistoryIndex: $overlayState.get().agentsInitialHistoryIndex,
    journey: $overlayState.get().journey,
    modelPicker: $overlayState.get().modelPicker,
    petPicker: $overlayState.get().petPicker,
    pluginsHub: $overlayState.get().pluginsHub,
    sessions: $overlayState.get().sessions,
    skillsHub: $overlayState.get().skillsHub
  })
}
