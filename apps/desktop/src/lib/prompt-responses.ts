export interface OwnedPromptResponse {
  requestId: string
  sessionId?: null | string
}

export interface ApprovalResolutionResponse {
  request_id?: string
  resolved?: boolean | number
}

export function ownedPromptResponseParams<T extends Record<string, unknown>>(
  prompt: OwnedPromptResponse,
  values: T
): T & { request_id: string; session_id: string | undefined } {
  return {
    ...values,
    request_id: prompt.requestId,
    session_id: prompt.sessionId ?? undefined
  }
}

export function approvalResponseResolved(
  response: ApprovalResolutionResponse | null | undefined,
  expectedRequestId: string
): boolean {
  const positive =
    response?.resolved === true ||
    (typeof response?.resolved === 'number' && Number.isFinite(response.resolved) && response.resolved > 0)

  return positive && response?.request_id === expectedRequestId
}

export function promptResponseMatches(
  response: { request_id?: string } | null | undefined,
  expectedRequestId: string
): boolean {
  return response?.request_id === expectedRequestId
}
