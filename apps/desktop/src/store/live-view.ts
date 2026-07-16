import { atom } from 'nanostores'

import type { GatewayEventPayload } from '@/lib/chat-messages'

import { PREVIEW_PANE_ID } from './layout'
import { setPaneOpen } from './panes'

export type LiveViewKind = 'browser' | 'desktop'
export type LiveViewPresentation = 'docked' | 'hidden' | 'pip'
export type LiveViewStatus = 'complete' | 'error' | 'running'

export interface LiveViewAction {
  activityId?: string
  completedAt?: number
  detail?: string
  durationS?: number
  id: string
  startedAt: number
  status: LiveViewStatus
  toolName: string
}

export interface LiveViewState {
  actions: LiveViewAction[]
  activityId?: string
  frameUrl?: string
  kind: LiveViewKind
  paused: boolean
  pipVisible?: boolean
  presentation: LiveViewPresentation
  sessionId: string
  status: LiveViewStatus
  streaming?: boolean
  target?: string
  updatedAt: number
}

export interface LiveViewOpenRequest {
  sessionId: string
}

export type LiveViewControl =
  | { sessionId: string; type: 'closed' | 'dock' | 'hide' | 'ready' }
  | { paused: boolean; sessionId: string; type: 'pause' }
  | { sessionId: string; type: 'visibility'; visible: boolean }

const MAX_ACTIONS = 16
const MAX_SESSIONS = 24
const MAX_FRAME_URL_CHARS = 4_000_000
const MAX_TEXT_CHARS = 1_024
let activitySequence = 0
let pipRequestSequence = 0
const pendingPipRequests = new Map<string, number>()

export const $liveViews = atom<Record<string, LiveViewState>>({})
/** High-frequency Browser frames live outside session metadata so route-level subscribers stay cold. */
export const $liveViewStreamFrames = atom<Record<string, string>>({})

function acceptedImageDataUrl(value: string | undefined): string | undefined {
  if (
    !value ||
    value.length > MAX_FRAME_URL_CHARS ||
    (!value.startsWith('data:image/jpeg;base64,') && !value.startsWith('data:image/png;base64,'))
  ) {
    return undefined
  }

  return value
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  return value as Record<string, unknown>
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== 'string') {
    return value
  }

  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

function firstString(record: Record<string, unknown> | null, keys: readonly string[]): string | undefined {
  if (!record) {
    return undefined
  }

  for (const key of keys) {
    const value = record[key]

    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }

  return undefined
}

function boundedText(value: string | undefined): string | undefined {
  return value?.trim().slice(0, MAX_TEXT_CHARS) || undefined
}

function firstBoundedString(record: Record<string, unknown> | null, keys: readonly string[]): string | undefined {
  return boundedText(firstString(record, keys))
}

export function isVisualToolName(name: string | undefined): boolean {
  return name === 'computer_use' || Boolean(name?.startsWith('browser_'))
}

export function liveViewKindForTool(name: string): LiveViewKind {
  return name === 'computer_use' ? 'desktop' : 'browser'
}

function imageUrlFromValue(value: unknown, depth = 0): string | undefined {
  if (depth > 5) {
    return undefined
  }

  if (typeof value === 'string') {
    return acceptedImageDataUrl(value)
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const found = imageUrlFromValue(item, depth + 1)

      if (found) {
        return found
      }
    }

    return undefined
  }

  const record = asRecord(value)

  if (!record) {
    return undefined
  }

  const direct = firstString(record, ['url', 'data_url', 'dataUrl'])

  const acceptedDirect = acceptedImageDataUrl(direct)

  if (acceptedDirect) {
    return acceptedDirect
  }

  for (const key of ['image_url', 'imageUrl', 'content', 'image', 'screenshot']) {
    if (!(key in record)) {
      continue
    }

    const found = imageUrlFromValue(record[key], depth + 1)

    if (found) {
      return found
    }
  }

  return undefined
}

/** Extract a visual frame without retaining or stringifying unrelated tool output. */
export function liveViewFrameFromResult(result: unknown): string | undefined {
  return imageUrlFromValue(parseMaybeJson(result))
}

function toolDetail(name: string, payload: GatewayEventPayload): string | undefined {
  const args = asRecord(parseMaybeJson(payload.args ?? payload.arguments ?? payload.input))
  const result = asRecord(parseMaybeJson(payload.result))

  if (name === 'computer_use') {
    return firstBoundedString(args, ['action', 'command', 'app', 'window']) ?? boundedText(payload.context)
  }

  return (
    firstBoundedString(args, ['url', 'selector', 'ref', 'direction', 'key', 'question']) ??
    firstBoundedString(result, ['url', 'title']) ??
    boundedText(payload.context)
  )
}

function toolTarget(name: string, payload: GatewayEventPayload, current?: string): string | undefined {
  const args = asRecord(parseMaybeJson(payload.args ?? payload.arguments ?? payload.input))
  const result = asRecord(parseMaybeJson(payload.result))

  if (name === 'computer_use') {
    return (
      firstBoundedString(args, ['app', 'window']) ??
      firstBoundedString(result, ['app', 'window_title']) ??
      current
    )
  }

  return firstBoundedString(result, ['title', 'url']) ?? firstBoundedString(args, ['url']) ?? current
}

function resultFailed(result: unknown, payloadError: unknown): boolean {
  if (payloadError) {
    return true
  }

  const record = asRecord(parseMaybeJson(result))

  return record?.success === false || Boolean(record?.error)
}

function clearLiveViewStreamFrames(sessionIds: readonly string[]): void {
  if (sessionIds.length === 0) {
    return
  }

  const current = $liveViewStreamFrames.get()
  const next = { ...current }
  let changed = false

  for (const sessionId of sessionIds) {
    if (sessionId in next) {
      delete next[sessionId]
      changed = true
    }
  }

  if (changed) {
    $liveViewStreamFrames.set(next)
  }
}

function boundedViews(next: Record<string, LiveViewState>): {
  evictedSessionIds: string[]
  views: Record<string, LiveViewState>
} {
  const entries = Object.entries(next)

  if (entries.length <= MAX_SESSIONS) {
    return { evictedSessionIds: [], views: next }
  }

  const removable = [...entries].sort((a, b) => {
    const aPip = a[1].presentation === 'pip' ? 1 : 0
    const bPip = b[1].presentation === 'pip' ? 1 : 0

    return aPip - bPip || a[1].updatedAt - b[1].updatedAt
  })

  const evictedSessionIds = removable.slice(0, entries.length - MAX_SESSIONS).map(([sessionId]) => sessionId)
  const trimmed = { ...next }

  for (const sessionId of evictedSessionIds) {
    delete trimmed[sessionId]
  }

  return { evictedSessionIds, views: trimmed }
}

function setLiveView(sessionId: string, updater: (current: LiveViewState | undefined) => LiveViewState): LiveViewState {
  const current = $liveViews.get()
  const nextState = updater(current[sessionId])
  const { evictedSessionIds, views } = boundedViews({ ...current, [sessionId]: nextState })

  $liveViews.set(views)
  clearLiveViewStreamFrames(evictedSessionIds)

  for (const evictedSessionId of evictedSessionIds) {
    if (typeof window !== 'undefined') {
      void window.hermesDesktop?.liveView?.close(evictedSessionId)
    }
  }

  if (views[sessionId]) {
    publishLiveViewToPip(nextState)
  }

  return nextState
}

function publishLiveViewToPip(state: LiveViewState): void {
  if (state.presentation === 'pip' && typeof window !== 'undefined') {
    const streamFrame = $liveViewStreamFrames.get()[state.sessionId]
    window.hermesDesktop?.liveView?.pushState(streamFrame ? { ...state, frameUrl: streamFrame } : state)
  }
}

function nextActivityId(): string {
  activitySequence += 1

  return `activity-${activitySequence}`
}

function aggregateLiveViewStatus(actions: readonly LiveViewAction[], activityId?: string): LiveViewStatus {
  const currentActions = activityId ? actions.filter(action => action.activityId === activityId) : actions

  if (currentActions.some(action => action.status === 'running')) {
    return 'running'
  }

  if (currentActions.some(action => action.status === 'error')) {
    return 'error'
  }

  return 'complete'
}

export function startLiveViewTool(sessionId: string, payload: GatewayEventPayload): void {
  const name = payload.name ?? ''

  if (!sessionId || !isVisualToolName(name)) {
    return
  }

  const now = Date.now()
  const id = String(payload.tool_id || payload.tool_call_id || `${name}:${now}`)
  const kind = liveViewKindForTool(name)
  const detail = toolDetail(name, payload)
  const current = $liveViews.get()[sessionId]

  if (kind === 'desktop' || current?.kind !== kind) {
    clearLiveViewStreamFrames([sessionId])
  }

  const next = setLiveView(sessionId, state => {
    const hasRunningAction = state?.actions.some(action => action.status === 'running') ?? false
    const continuingHiddenRun = state?.presentation === 'hidden' && hasRunningAction
    const presentation = state?.presentation === 'pip' || continuingHiddenRun ? state.presentation : 'docked'
    const activityId = hasRunningAction ? (state?.activityId ?? nextActivityId()) : nextActivityId()

    const actions = [
      ...(state?.actions ?? []).filter(action => action.id !== id),
      {
        activityId,
        detail,
        id,
        startedAt: now,
        status: 'running' as const,
        toolName: name
      }
    ].slice(-MAX_ACTIONS)

    return {
      actions,
      activityId,
      frameUrl: kind === state?.kind ? state.frameUrl : undefined,
      kind,
      paused: state?.paused ?? false,
      pipVisible: state?.presentation === 'pip' ? state.pipVisible : undefined,
      presentation,
      sessionId,
      status: 'running',
      streaming: kind === state?.kind ? state.streaming : false,
      target: toolTarget(name, payload, kind === state?.kind ? state.target : undefined),
      updatedAt: now
    }
  })

  if (next.presentation === 'docked') {
    setPaneOpen(PREVIEW_PANE_ID, true)
  }
}

export function completeLiveViewTool(sessionId: string, payload: GatewayEventPayload): void {
  const name = payload.name ?? ''

  if (!sessionId || !isVisualToolName(name)) {
    return
  }

  const current = $liveViews.get()[sessionId]
  const kind = liveViewKindForTool(name)

  if (!current || current.kind !== kind) {
    startLiveViewTool(sessionId, payload)
  }

  const now = Date.now()
  const id = String(payload.tool_id || payload.tool_call_id || '')
  const failed = resultFailed(payload.result, payload.error)
  const frameUrl = liveViewFrameFromResult(payload.result)

  setLiveView(sessionId, state => {
    const base = state ?? {
      actions: [],
      activityId: nextActivityId(),
      kind: liveViewKindForTool(name),
      paused: false,
      presentation: 'docked' as const,
      sessionId,
      status: 'running' as const,
      updatedAt: now
    }

    const hadRunningAction = base.actions.some(action => action.status === 'running')
    let activityId = base.activityId
    let matched = false

    let actions = base.actions.map(action => {
      if ((id && action.id === id) || (!id && !matched && action.toolName === name && action.status === 'running')) {
        matched = true

        return {
          ...action,
          completedAt: now,
          durationS: payload.duration_s,
          status: failed ? ('error' as const) : ('complete' as const)
        }
      }

      return action
    })

    if (!matched) {
      if (!hadRunningAction) {
        activityId = nextActivityId()
      }

      actions = [
        ...actions,
        {
          activityId,
          completedAt: now,
          detail: toolDetail(name, payload),
          durationS: payload.duration_s,
          id: id || `${name}:${now}`,
          startedAt: typeof payload.duration_s === 'number' ? now - payload.duration_s * 1_000 : now,
          status: failed ? ('error' as const) : ('complete' as const),
          toolName: name
        }
      ].slice(-MAX_ACTIONS)
    }

    const shouldStoreFrame = !base.paused && base.presentation !== 'hidden' && frameUrl

    if (shouldStoreFrame) {
      clearLiveViewStreamFrames([sessionId])
    }

    return {
      ...base,
      actions,
      activityId,
      frameUrl: shouldStoreFrame || base.frameUrl,
      status: aggregateLiveViewStatus(actions, activityId),
      target: toolTarget(name, payload, base.target),
      updatedAt: now
    }
  })
}

export function finishLiveViewTurn(sessionId: string, failed = false): void {
  const current = $liveViews.get()[sessionId]

  if (!current || (!current.actions.some(action => action.status === 'running') && current.status !== 'running')) {
    return
  }

  const now = Date.now()

  setLiveView(sessionId, state => {
    const base = state ?? current

    const actions = base.actions.map(action =>
      action.status === 'running'
        ? {
            ...action,
            completedAt: now,
            status: failed ? ('error' as const) : ('complete' as const)
          }
        : action
    )

    return {
      ...base,
      actions,
      status: failed ? 'error' : aggregateLiveViewStatus(actions, base.activityId),
      updatedAt: now
    }
  })
}

export function setLiveViewPaused(sessionId: string, paused: boolean): void {
  const current = $liveViews.get()[sessionId]

  if (!current) {
    return
  }

  setLiveView(sessionId, state => ({ ...(state ?? current), paused, updatedAt: Date.now() }))
}

export function setLiveViewStreaming(sessionId: string, streaming: boolean): void {
  const current = $liveViews.get()[sessionId]

  if (!current || current.streaming === streaming) {
    return
  }

  setLiveView(sessionId, state => ({ ...(state ?? current), streaming, updatedAt: Date.now() }))
}

export function setLiveViewStreamFrame(sessionId: string, frameUrl: string): void {
  const current = $liveViews.get()[sessionId]
  const acceptedFrame = acceptedImageDataUrl(frameUrl)

  if (
    !current ||
    current.kind !== 'browser' ||
    current.paused ||
    current.presentation === 'hidden' ||
    !acceptedFrame?.startsWith('data:image/jpeg;base64,')
  ) {
    return
  }

  const frames = $liveViewStreamFrames.get()

  if (frames[sessionId] === acceptedFrame) {
    return
  }

  $liveViewStreamFrames.set({ ...frames, [sessionId]: acceptedFrame })
  publishLiveViewToPip(current)
}

export function hideLiveView(sessionId: string): void {
  const current = $liveViews.get()[sessionId]

  if (!current) {
    return
  }

  pendingPipRequests.delete(sessionId)
  clearLiveViewStreamFrames([sessionId])
  setLiveView(sessionId, state => ({
    ...(state ?? current),
    frameUrl: undefined,
    pipVisible: undefined,
    presentation: 'hidden',
    streaming: false,
    updatedAt: Date.now()
  }))

  if (typeof window !== 'undefined') {
    void window.hermesDesktop?.liveView?.close(sessionId)
  }
}

export function dockLiveView(sessionId: string): void {
  const current = $liveViews.get()[sessionId]

  if (!current) {
    return
  }

  pendingPipRequests.delete(sessionId)
  setLiveView(sessionId, state => ({
    ...(state ?? current),
    pipVisible: undefined,
    presentation: 'docked',
    updatedAt: Date.now()
  }))
  setPaneOpen(PREVIEW_PANE_ID, true)

  if (typeof window !== 'undefined') {
    void window.hermesDesktop?.liveView?.close(sessionId)
  }
}

export async function popOutLiveView(sessionId: string): Promise<boolean> {
  const current = $liveViews.get()[sessionId]

  if (!current || typeof window === 'undefined' || !window.hermesDesktop?.liveView) {
    return false
  }

  pipRequestSequence += 1
  const requestId = pipRequestSequence
  pendingPipRequests.set(sessionId, requestId)

  try {
    const result = await window.hermesDesktop.liveView.open({ sessionId })
    const latest = $liveViews.get()[sessionId]

    if (pendingPipRequests.get(sessionId) !== requestId) {
      return false
    }

    pendingPipRequests.delete(sessionId)

    if (!result.ok || !latest || latest.presentation !== 'docked') {
      if (result.ok && latest?.presentation !== 'pip') {
        void window.hermesDesktop.liveView.close(sessionId)
      }

      return false
    }

    setLiveView(sessionId, state => ({ ...(state ?? latest), presentation: 'pip', updatedAt: Date.now() }))

    return true
  } catch {
    if (pendingPipRequests.get(sessionId) === requestId) {
      pendingPipRequests.delete(sessionId)
    }

    return false
  }
}

let controlUnsubscribe: (() => void) | null = null

export function initLiveViewBridge(): () => void {
  if (typeof window === 'undefined') {
    return () => {}
  }

  const api = window.hermesDesktop?.liveView

  if (!api || controlUnsubscribe) {
    return () => {}
  }

  controlUnsubscribe = api.onControl(control => {
    const current = $liveViews.get()[control.sessionId]

    if (!current) {
      return
    }

    if (control.type === 'ready') {
      publishLiveViewToPip(current)
    } else if (control.type === 'dock' || control.type === 'closed') {
      dockLiveView(control.sessionId)
    } else if (control.type === 'hide') {
      hideLiveView(control.sessionId)
    } else if (control.type === 'pause') {
      setLiveViewPaused(control.sessionId, control.paused)
    } else if (control.type === 'visibility') {
      setLiveView(control.sessionId, state => ({
        ...(state ?? current),
        pipVisible: control.visible,
        updatedAt: Date.now()
      }))
    }
  })

  return () => {
    controlUnsubscribe?.()
    controlUnsubscribe = null
  }
}

export function resetLiveViewsForTest(): void {
  $liveViews.set({})
  $liveViewStreamFrames.set({})
  activitySequence = 0
  pipRequestSequence = 0
  pendingPipRequests.clear()
}
