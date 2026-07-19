import { randomUUID } from 'node:crypto'
import { closeSync, fsyncSync, openSync, readFileSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export interface TuiLaunchContext {
  active_session_file?: string
  checkpoints?: boolean
  cwd?: string
  dashboard?: boolean
  gateway_url?: string
  ignore_rules?: boolean
  ignore_user_config?: boolean
  image?: string
  max_turns?: number | null
  model?: string
  pass_session_id?: boolean
  provider?: string
  query?: string
  resume?: string
  sidecar_url?: string
  skills?: string[]
  terminal_background?: string
  tool_progress?: string
  toolsets?: string[]
  version: 1
}

const stringValue = (raw: Record<string, unknown>, key: string) => {
  const value = raw[key]

  if (value === undefined) {
    return ''
  }

  if (typeof value !== 'string') {
    throw new Error(`TUI launch context field ${key} must be a string`)
  }

  return value
}

const booleanValue = (raw: Record<string, unknown>, key: string) => {
  const value = raw[key]

  if (value === undefined) {
    return false
  }

  if (typeof value !== 'boolean') {
    throw new Error(`TUI launch context field ${key} must be a boolean`)
  }

  return value
}

const stringList = (raw: Record<string, unknown>, key: string) => {
  const value = raw[key]

  if (value === undefined) {
    return []
  }

  if (!Array.isArray(value) || !value.every(item => typeof item === 'string')) {
    throw new Error(`TUI launch context field ${key} must be a string list`)
  }

  return value.filter(item => Boolean(item.trim()))
}

export const normalizeTuiLaunchContext = (value: unknown): TuiLaunchContext => {
  const raw = value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}

  if (raw.version !== 1) {
    throw new Error('unsupported TUI launch context version')
  }

  if (
    raw.max_turns !== undefined &&
    raw.max_turns !== null &&
    (typeof raw.max_turns !== 'number' || !Number.isSafeInteger(raw.max_turns) || raw.max_turns <= 0)
  ) {
    throw new Error('TUI launch context field max_turns must be a positive integer')
  }

  const maxTurns = typeof raw.max_turns === 'number' ? raw.max_turns : null

  return {
    active_session_file: stringValue(raw, 'active_session_file'),
    checkpoints: booleanValue(raw, 'checkpoints'),
    cwd: stringValue(raw, 'cwd'),
    dashboard: booleanValue(raw, 'dashboard'),
    gateway_url: stringValue(raw, 'gateway_url'),
    ignore_rules: booleanValue(raw, 'ignore_rules'),
    ignore_user_config: booleanValue(raw, 'ignore_user_config'),
    image: stringValue(raw, 'image'),
    max_turns: maxTurns,
    model: stringValue(raw, 'model'),
    pass_session_id: booleanValue(raw, 'pass_session_id'),
    provider: stringValue(raw, 'provider'),
    query: stringValue(raw, 'query'),
    resume: stringValue(raw, 'resume'),
    sidecar_url: stringValue(raw, 'sidecar_url'),
    skills: stringList(raw, 'skills'),
    terminal_background: stringValue(raw, 'terminal_background'),
    tool_progress: stringValue(raw, 'tool_progress'),
    toolsets: stringList(raw, 'toolsets'),
    version: 1
  }
}

const assertOwnerOnlyDescriptor = (path: string) => {
  const stat = statSync(path)

  if (!stat.isFile()) {
    throw new Error('TUI launch context is not a regular file')
  }

  if (process.platform !== 'win32') {
    if ((stat.mode & 0o077) !== 0) {
      throw new Error('TUI launch context must be owner-only')
    }

    if (typeof process.getuid === 'function' && stat.uid !== process.getuid()) {
      throw new Error('TUI launch context owner does not match this process')
    }
  }
}

export const consumeTuiLaunchContext = (path?: string): TuiLaunchContext => {
  if (!path) {
    return { version: 1 }
  }

  try {
    assertOwnerOnlyDescriptor(path)

    return normalizeTuiLaunchContext(JSON.parse(readFileSync(path, 'utf8')))
  } finally {
    try {
      unlinkSync(path)
    } catch {
      // The Python launcher also performs best-effort cleanup on exit.
    }
  }
}

export const writeTuiLaunchContext = (context: TuiLaunchContext): string => {
  const path = join(tmpdir(), `tui-launch-${process.pid}-${randomUUID()}.json`)
  const fd = openSync(path, 'wx', 0o600)

  try {
    writeFileSync(fd, JSON.stringify(normalizeTuiLaunchContext(context)), 'utf8')
    fsyncSync(fd)
  } catch (error) {
    closeSync(fd)

    try {
      unlinkSync(path)
    } catch {
      // Preserve the original write error.
    }

    throw error
  }

  closeSync(fd)

  return path
}
