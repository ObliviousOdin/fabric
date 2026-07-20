import { describe, expect, it } from 'vitest'

import {
  approvalResponseResolved,
  ownedPromptResponseParams,
  promptResponseMatches
} from '../lib/promptResponses.js'

describe('prompt response contracts', () => {
  it('includes the exact request and owning session ids', () => {
    expect(
      ownedPromptResponseParams({ requestId: 'approval-1', sessionId: 'session-1' }, { choice: 'once' })
    ).toEqual({ choice: 'once', request_id: 'approval-1', session_id: 'session-1' })
  })

  it('only accepts a positive approval resolution receipt', () => {
    expect(approvalResponseResolved({ request_id: 'approval-1', resolved: 1 }, 'approval-1')).toBe(true)
    expect(approvalResponseResolved({ resolved: true }, 'approval-1')).toBe(false)
    expect(approvalResponseResolved({ request_id: 'other', resolved: 1 }, 'approval-1')).toBe(false)
    expect(approvalResponseResolved({ resolved: 0 }, 'approval-1')).toBe(false)
    expect(approvalResponseResolved({ resolved: false }, 'approval-1')).toBe(false)
    expect(approvalResponseResolved({}, 'approval-1')).toBe(false)
    expect(approvalResponseResolved(null, 'approval-1')).toBe(false)
  })

  it('requires the exact request id for every blocking prompt receipt', () => {
    expect(promptResponseMatches({ request_id: 'prompt-1' }, 'prompt-1')).toBe(true)
    expect(promptResponseMatches({ request_id: 'other' }, 'prompt-1')).toBe(false)
    expect(promptResponseMatches({}, 'prompt-1')).toBe(false)
    expect(promptResponseMatches(null, 'prompt-1')).toBe(false)
  })
})
