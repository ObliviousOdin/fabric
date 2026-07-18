export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

export function compactPreview(value: unknown, max = 72): string {
  let raw: unknown

  if (typeof value === 'string') {
    raw = value
  } else {
    raw = parseMaybeObject(value).context
  }

  if (typeof raw !== 'string') {
    if (raw == null) {
      raw = ''
    } else {
      try {
        raw = JSON.stringify(raw)
      } catch {
        raw = String(raw)
      }
    }
  }

  const line = (raw as string).replace(/\s+/g, ' ').trim()

  return line.length > max ? `${line.slice(0, max - 1)}…` : line
}

export function contextValue(value: unknown): string {
  const row = parseMaybeObject(value)

  if (typeof row.context === 'string') {
    return row.context
  }

  if (typeof row.preview === 'string') {
    return row.preview
  }

  return typeof value === 'string' ? value : ''
}

// Each tool result is server-capped (~100KB), but a turn over a big directory
// stacks many rows; painting/serializing them all floods the renderer (freeze,
// then OOM). Clamp every inline-painted payload to a bounded slice — the row's
// Copy button still reads the uncapped `view.detail` for the full output.
export const MAX_TOOL_RENDER_CHARS = 20_000

const INLINE_IMAGE_OMITTED = '[inline image data omitted]'

const EMBEDDED_DATA_IMAGE_RE = /data:image\/[a-z0-9.+-]+(?:;[^,\s"'\\]+)*;base64,[a-z0-9+/_=\r\n-]+/gi

export function clampForDisplay(value: string, max = MAX_TOOL_RENDER_CHARS): string {
  if (value.length <= max) {
    return value
  }

  const omitted = value.length - max

  return `${value.slice(0, max)}\n\n… ${omitted.toLocaleString()} more characters truncated — use Copy for the full output.`
}

/**
 * Keep screenshot payloads useful in technical traces without serializing
 * their base64 bytes into the DOM. Most multimodal results carry the data URL
 * as the entire string, while stringified/embedded envelopes need the regex
 * fallback.
 */
export function redactInlineImageData(value: string): string {
  const lower = value.toLowerCase()

  if (!lower.includes('data:image/')) {
    return value
  }

  if (lower.startsWith('data:image/')) {
    const comma = value.indexOf(',')

    if (comma > 0 && lower.slice(0, comma).includes(';base64')) {
      return `${value.slice(0, comma + 1)}${INLINE_IMAGE_OMITTED}`
    }
  }

  return value.replace(EMBEDDED_DATA_IMAGE_RE, match => {
    const comma = match.indexOf(',')

    return comma >= 0 ? `${match.slice(0, comma + 1)}${INLINE_IMAGE_OMITTED}` : INLINE_IMAGE_OMITTED
  })
}

export function prettyJson(value: unknown): string {
  const raw =
    typeof value === 'string'
      ? redactInlineImageData(value)
      : JSON.stringify(
          value,
          (_key, nested) => (typeof nested === 'string' ? redactInlineImageData(nested) : nested),
          2
        )

  return clampForDisplay(raw ?? '')
}

export function parseMaybeObject(value: unknown): Record<string, unknown> {
  if (isRecord(value)) {
    return value
  }

  if (typeof value !== 'string' || !value.trim()) {
    return {}
  }

  try {
    const parsed = JSON.parse(value)

    return isRecord(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

export function unwrapToolPayload(value: unknown): unknown {
  const record = parseMaybeObject(value)

  for (const key of ['data', 'result', 'output', 'response', 'payload']) {
    const payload = record[key]

    if (payload !== undefined && payload !== null) {
      return payload
    }
  }

  return value
}

export function numberValue(value: unknown): null | number {
  const n = typeof value === 'number' ? value : Number(value)

  return Number.isFinite(n) ? n : null
}

export function formatDurationSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return ''
  }

  if (seconds < 1) {
    const ms = Math.max(1, Math.round(seconds * 1000))

    return `${ms}ms`
  }

  if (seconds < 60) {
    return `${seconds.toFixed(seconds >= 10 ? 0 : 1)}s`
  }

  const wholeSeconds = Math.round(seconds)
  const minutes = Math.floor(wholeSeconds / 60)
  const remSeconds = wholeSeconds % 60

  if (minutes < 60) {
    return remSeconds ? `${minutes}m ${remSeconds}s` : `${minutes}m`
  }

  const hours = Math.floor(minutes / 60)
  const remMinutes = minutes % 60

  return remMinutes ? `${hours}h ${remMinutes}m` : `${hours}h`
}
