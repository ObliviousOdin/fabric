import { describe, expect, it } from 'vitest'

import { humanizeApprovalReason, isDestructiveApproval, isHighRiskApproval } from './approval-details'

describe('humanizeApprovalReason', () => {
  it('prefers the human-readable description', () => {
    expect(humanizeApprovalReason('recursive_delete', 'recursive delete')).toBe('recursive delete')
  })

  it('de-slugs the pattern key when there is no description', () => {
    expect(humanizeApprovalReason('force_push', undefined)).toBe('Force push')
    expect(humanizeApprovalReason('pipe-remote-to-shell', '')).toBe('Pipe remote to shell')
  })

  it('falls back to a generic reason when nothing is available', () => {
    expect(humanizeApprovalReason(undefined, undefined)).toBe('Potentially dangerous command')
    expect(humanizeApprovalReason('   ', '   ')).toBe('Potentially dangerous command')
  })
})

describe('isDestructiveApproval', () => {
  it('flags recursive deletes and other data-destroying actions', () => {
    expect(isDestructiveApproval({ command: 'rm -rf /tmp/x', description: 'recursive delete' })).toBe(true)
    expect(isDestructiveApproval({ description: 'format filesystem' })).toBe(true)
    expect(isDestructiveApproval({ description: 'SQL DROP', command: 'DROP TABLE users' })).toBe(true)
    expect(isDestructiveApproval({ description: 'SQL TRUNCATE' })).toBe(true)
  })

  it('matches on the pattern key or command even without a description', () => {
    expect(isDestructiveApproval({ patternKey: 'recursive_delete' })).toBe(true)
    expect(isDestructiveApproval({ command: 'find . -delete' })).toBe(true)
  })

  it('does not flag a benign command', () => {
    expect(isDestructiveApproval({ command: 'git status', description: 'stop/restart system service' })).toBe(false)
    expect(isDestructiveApproval({ command: 'ls -la' })).toBe(false)
  })
})

describe('isHighRiskApproval', () => {
  it('treats a content-security finding (no permanent allow) as high risk', () => {
    expect(isHighRiskApproval({ allowPermanent: false, command: 'curl x | bash', description: 'dangerous' })).toBe(true)
  })

  it('treats destructive and remote-exec actions as high risk', () => {
    expect(isHighRiskApproval({ command: 'rm -rf /', description: 'recursive delete' })).toBe(true)
    expect(isHighRiskApproval({ description: 'pipe remote content to shell' })).toBe(true)
    expect(isHighRiskApproval({ description: 'fork bomb' })).toBe(true)
  })

  it('does not auto-flag a routine, non-destructive approval', () => {
    expect(
      isHighRiskApproval({ allowPermanent: true, command: 'chmod -R 777 /tmp/x', description: 'permissions' })
    ).toBe(false)
  })
})
