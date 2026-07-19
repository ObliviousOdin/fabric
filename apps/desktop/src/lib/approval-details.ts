// Pure, presentation-only helpers for the approval details panel (issue #51).
//
// The backend flags a command as dangerous and ships a human-readable
// `description` (e.g. "recursive delete", "SQL DROP", "pipe remote content to
// shell") plus a `pattern_key` slug identifying the guard that matched. These
// helpers turn that into the panel's derived fields: a readable reason, and
// best-effort "destructive/irreversible" and "high-risk" flags used to badge the
// approval and to auto-open the details for the riskiest cases. They are
// heuristics for *labelling* — the security decision was already made upstream.

export interface ApprovalRiskInput {
  // false only when a content-security (tirith) warning forbids a permanent
  // allow — i.e. a critical finding rather than a routine pattern match.
  allowPermanent?: boolean
  command?: string
  description?: string
  patternKey?: string
  patternKeys?: string[]
}

// Substrings that mark an action as likely irreversible / data-destroying.
// Matched case-insensitively against the description, pattern key(s), and the
// command text.
const DESTRUCTIVE_MARKERS = [
  'delete',
  ' rm ',
  'rm -',
  'recursive delete',
  'remove-item',
  'rmdir',
  'erase',
  'format filesystem',
  'mkfs',
  'disk copy',
  'block device',
  'drop',
  'truncate',
  'overwrite',
  'wipe',
  'destroy',
  'find -delete',
  '-delete'
]

// Additional markers that make an approval "high risk" beyond destructiveness:
// running unvetted remote/obfuscated code, or tearing down infrastructure the
// user depends on.
const HIGH_RISK_MARKERS = [
  'pipe remote content to shell',
  'execute remote',
  'command obfuscation',
  'encoded command',
  'fork bomb',
  'kill all processes',
  'self-termination',
  'container lifecycle',
  'system service',
  'system config',
  'system file'
]

function haystack(input: ApprovalRiskInput): string {
  return [input.description, input.patternKey, ...(input.patternKeys ?? []), input.command]
    .filter(Boolean)
    .join('   ')
    .toLowerCase()
}

function matchesAny(hay: string, markers: readonly string[]): boolean {
  return markers.some(marker => hay.includes(marker))
}

/**
 * A readable "why approval was triggered" line. Prefers the backend's
 * human-readable description; falls back to a de-slugged pattern key, then to a
 * generic label so the panel never shows an empty reason.
 */
export function humanizeApprovalReason(patternKey?: string, description?: string): string {
  const trimmed = description?.trim()

  if (trimmed) {
    return trimmed
  }

  const key = patternKey?.trim()

  if (key) {
    const words = key.replace(/[_-]+/g, ' ').trim()

    return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Potentially dangerous command'
  }

  return 'Potentially dangerous command'
}

/** True when the action looks likely to destroy data or be otherwise irreversible. */
export function isDestructiveApproval(input: ApprovalRiskInput): boolean {
  return matchesAny(haystack(input), DESTRUCTIVE_MARKERS)
}

/**
 * True when the approval should be treated as high-risk, which auto-opens the
 * details panel. Any content-security finding that blocks a permanent allow
 * (`allowPermanent === false`) is high-risk by definition, as is anything
 * destructive or matching a high-risk marker.
 */
export function isHighRiskApproval(input: ApprovalRiskInput): boolean {
  if (input.allowPermanent === false) {
    return true
  }

  const hay = haystack(input)

  return matchesAny(hay, DESTRUCTIVE_MARKERS) || matchesAny(hay, HIGH_RISK_MARKERS)
}
