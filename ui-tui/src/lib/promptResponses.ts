import type { ApprovalRespondResponse } from '../gatewayTypes.js'

interface OwnedPrompt {
  requestId: string
  sessionId?: string
}

interface PromptResponseReceipt {
  request_id?: string
}

export const ownedPromptResponseParams = <T extends Record<string, unknown>>(prompt: OwnedPrompt, values: T) => ({
  ...values,
  request_id: prompt.requestId,
  session_id: prompt.sessionId
})

export const approvalResponseResolved = (
  response: ApprovalRespondResponse | null | undefined,
  expectedRequestId: string
): boolean => {
  const positive =
    response?.resolved === true ||
    (typeof response?.resolved === 'number' && Number.isFinite(response.resolved) && response.resolved > 0)

  return positive && response?.request_id === expectedRequestId
}

export const promptResponseMatches = (
  response: PromptResponseReceipt | null | undefined,
  expectedRequestId: string
): boolean => response?.request_id === expectedRequestId
