import { readDesktopFileDataUrl } from '@/lib/desktop-fs'
import { filePathFromMediaPath, isRemoteGateway, mediaExternalUrl } from '@/lib/media'
import type { SessionInfo, SessionMessage } from '@/types/hermes'

export type ArtifactKind = 'image' | 'file' | 'link'
export type ArtifactFilter = 'all' | ArtifactKind
export const ARTIFACT_FILTERS: readonly ArtifactFilter[] = ['all', 'image', 'file', 'link']

export interface ArtifactRecord {
  id: string
  kind: ArtifactKind
  value: string
  href: string
  label: string
  sessionId: string
  sessionTitle: string
  timestamp: number
}

const MARKDOWN_IMAGE_RE = /!\[([^\]]*)\]\(([^)\s]+)\)/g
const MARKDOWN_LINK_RE = /\[([^\]]+)\]\(([^)\s]+)\)/g
const INLINE_CODE_RE = /`([^`\n]+)`/g
const URL_RE = /https?:\/\/[^\s<>"')]+/g
const PATH_RE = /(^|[\s("'`])((?:\/|~\/|\.\.?\/)[^\s"'`<>]+(?:\.[a-z0-9]{1,10})?)/gi

const RELATIVE_PATH_RE =
  /(^|[\s("'`])((?:[a-z0-9_@.+-]+\/)+[a-z0-9_@.+-]+\.[a-z0-9]{1,10})(?=$|[\s)"'`,;])/gi

const IMAGE_EXT_RE = /\.(?:png|jpe?g|gif|webp|svg|bmp|ico)(?:[?#].*)?$/i

const FILE_EXT_RE =
  /\.(?:png|jpe?g|gif|webp|svg|bmp|ico|pdf|txt|html?|json|md|csv|zip|tar|gz|mp3|wav|mp4|mov)(?:[?#].*)?$/i

const KEY_HINT_RE = /(path|file|url|image|artifact|output|download|result|target)/i

const WINDOWS_ABSOLUTE_PATH_RE = /^(?:[a-z]:[\\/]|\\\\)/i

function artifactSessionTitle(session: SessionInfo): string {
  return session.title?.trim() || session.preview?.trim() || 'Untitled session'
}

function normalizeValue(value: string): string {
  return value.trim().replace(/[),.;]+$/, '')
}

function parseMaybeJson(value: string): unknown {
  if (!value.trim()) {
    return null
  }

  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function looksLikePathOrUrl(value: string): boolean {
  return (
    value.startsWith('http://') ||
    value.startsWith('https://') ||
    value.startsWith('file://') ||
    value.startsWith('data:image/') ||
    value.startsWith('/') ||
    value.startsWith('./') ||
    value.startsWith('../') ||
    value.startsWith('~/')
  )
}

function looksLikeArtifact(value: string): boolean {
  if (/^(?:https?:\/\/|data:image\/)/.test(value)) {
    return true
  }

  if (FILE_EXT_RE.test(value)) {
    return true
  }

  return (value.startsWith('/') || WINDOWS_ABSOLUTE_PATH_RE.test(value)) && value.includes('.')
}

function resolveArtifactValue(value: string, cwd?: null | string): null | string {
  if (
    /^(?:https?:\/\/|data:|file:)/i.test(value) ||
    value.startsWith('/') ||
    value.startsWith('~/') ||
    WINDOWS_ABSOLUTE_PATH_RE.test(value)
  ) {
    return value
  }

  if (!cwd) {
    return null
  }

  const combined = `${cwd.replace(/\\/g, '/').replace(/\/+$/, '')}/${value.replace(/\\/g, '/')}`
  const absolute = combined.startsWith('/')
  const unc = combined.startsWith('//')
  const drive = /^[a-z]:\//i.test(combined)
  const rootDepth = unc ? 2 : drive ? 1 : 0
  const segments: string[] = []

  for (const segment of combined.split('/')) {
    if (!segment || segment === '.') {
      continue
    }

    if (segment === '..') {
      if (segments.length > rootDepth) {
        segments.pop()
      }

      continue
    }

    segments.push(segment)
  }

  return `${unc ? '//' : absolute ? '/' : ''}${segments.join('/')}`
}

function artifactKind(value: string): ArtifactKind {
  if (value.startsWith('data:image/') || IMAGE_EXT_RE.test(value)) {
    return 'image'
  }

  if (
    value.startsWith('/') ||
    value.startsWith('./') ||
    value.startsWith('../') ||
    value.startsWith('~/') ||
    value.startsWith('file://') ||
    WINDOWS_ABSOLUTE_PATH_RE.test(value)
  ) {
    return 'file'
  }

  return 'link'
}

function artifactHref(value: string): string {
  if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('data:')) {
    return value
  }

  if (/^[a-z]:[\\/]/i.test(value) && !isRemoteGateway()) {
    return `file:///${value.replace(/\\/g, '/')}`
  }

  if (/^(?:\\\\|\/\/)/.test(value) && !isRemoteGateway()) {
    return `file:${value.replace(/\\/g, '/')}`
  }

  if (value.startsWith('file://') || value.startsWith('/') || WINDOWS_ABSOLUTE_PATH_RE.test(value)) {
    return mediaExternalUrl(value)
  }

  return value
}

export async function artifactImageSrc(value: string, href = artifactHref(value)): Promise<string> {
  if (/^(?:https?|data):/i.test(value)) {
    return href
  }

  if (typeof window !== 'undefined' && window.fabricDesktop && isRemoteGateway()) {
    return readDesktopFileDataUrl(filePathFromMediaPath(value))
  }

  return href
}

function artifactLabel(value: string): string {
  try {
    const url = new URL(value)
    const item = url.pathname.split('/').filter(Boolean).pop()

    return item || value
  } catch {
    const parts = value.split(/[\\/]/).filter(Boolean)

    return parts.pop() || value
  }
}

function messageText(message: SessionMessage): string {
  if (typeof message.content === 'string' && message.content.trim()) {
    return message.content
  }

  if (typeof message.text === 'string' && message.text.trim()) {
    return message.text
  }

  if (typeof message.context === 'string' && message.context.trim()) {
    return message.context
  }

  return ''
}

function collectStringValues(
  value: unknown,
  keyPath: string,
  collector: (value: string, keyPath: string) => void
): void {
  if (typeof value === 'string') {
    collector(value, keyPath)

    return
  }

  if (Array.isArray(value)) {
    value.forEach((entry, index) => collectStringValues(entry, `${keyPath}.${index}`, collector))

    return
  }

  if (!value || typeof value !== 'object') {
    return
  }

  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    collectStringValues(child, keyPath ? `${keyPath}.${key}` : key, collector)
  }
}

function collectStructuredArtifactValues(value: unknown, pushValue: (value: string) => void): void {
  collectStringValues(value, '', (candidate, keyPath) => {
    const normalized = normalizeValue(candidate)

    if (!normalized) {
      return
    }

    if ((KEY_HINT_RE.test(keyPath) || looksLikePathOrUrl(normalized)) && looksLikeArtifact(normalized)) {
      pushValue(normalized)
    }
  })
}

function collectArtifactsFromText(text: string, pushValue: (value: string) => void): void {
  for (const match of text.matchAll(MARKDOWN_IMAGE_RE)) {
    pushValue(match[2] || '')
  }

  for (const match of text.matchAll(MARKDOWN_LINK_RE)) {
    const start = match.index ?? 0

    if (start > 0 && text[start - 1] === '!') {
      continue
    }

    const value = match[2] || ''

    if (looksLikeArtifact(value)) {
      pushValue(value)
    }
  }

  for (const match of text.matchAll(URL_RE)) {
    const value = match[0] || ''

    if (looksLikeArtifact(value)) {
      pushValue(value)
    }
  }

  for (const match of text.matchAll(INLINE_CODE_RE)) {
    const value = match[1] || ''

    if (looksLikeArtifact(value)) {
      pushValue(value)
    }
  }

  for (const match of text.matchAll(PATH_RE)) {
    pushValue(match[2] || '')
  }

  for (const match of text.matchAll(RELATIVE_PATH_RE)) {
    pushValue(match[2] || '')
  }
}

function collectArtifactsFromMessage(message: SessionMessage, pushValue: (value: string) => void): void {
  const text = messageText(message)

  if (text) {
    collectArtifactsFromText(text, pushValue)
  }

  if (message.role !== 'tool' && !Array.isArray(message.tool_calls)) {
    return
  }

  if (Array.isArray(message.tool_calls)) {
    for (const call of message.tool_calls) {
      collectStructuredArtifactValues(call, pushValue)

      if (!call || typeof call !== 'object') {
        continue
      }

      const record = call as Record<string, unknown>
      const fn = record.function && typeof record.function === 'object' ? (record.function as Record<string, unknown>) : null
      const rawArguments = fn?.arguments ?? record.arguments

      if (typeof rawArguments === 'string') {
        const parsedArguments = parseMaybeJson(rawArguments)

        if (parsedArguments !== null) {
          collectStructuredArtifactValues(parsedArguments, pushValue)
        }
      } else if (rawArguments !== undefined) {
        collectStructuredArtifactValues(rawArguments, pushValue)
      }
    }
  }

  const parsed = parseMaybeJson(text)

  if (parsed !== null) {
    collectStructuredArtifactValues(parsed, pushValue)
  }
}

export function collectArtifactsForSession(session: SessionInfo, messages: SessionMessage[]): ArtifactRecord[] {
  const found = new Map<string, ArtifactRecord>()
  const title = artifactSessionTitle(session)

  for (const message of messages) {
    if (message.role !== 'assistant' && message.role !== 'tool') {
      continue
    }

    collectArtifactsFromMessage(message, candidate => {
      const rawValue = normalizeValue(candidate)

      if (!rawValue || !looksLikeArtifact(rawValue)) {
        return
      }

      const value = resolveArtifactValue(rawValue, session.cwd)

      if (!value) {
        return
      }

      const key = `${session.id}:${value}`

      if (found.has(key)) {
        return
      }

      found.set(key, {
        id: key,
        kind: artifactKind(value),
        value,
        href: artifactHref(value),
        label: artifactLabel(value),
        sessionId: session.id,
        sessionTitle: title,
        timestamp: message.timestamp || session.last_active || session.started_at || Date.now()
      })
    })
  }

  return Array.from(found.values())
}
