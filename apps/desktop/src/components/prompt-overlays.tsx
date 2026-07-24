'use client'

import { useStore } from '@nanostores/react'
import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'

import { PendingApprovalFallback } from '@/components/assistant-ui/tool/approval'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { KeyRound, Loader2, Lock, MessageQuestion } from '@/lib/icons'
import { ownedPromptResponseParams, promptResponseMatches } from '@/lib/prompt-responses'
import { $clarifyRequest, clearClarifyRequest } from '@/store/clarify'
import { $gateway } from '@/store/gateway'
import { notifyError } from '@/store/notifications'
import { $secretRequest, $sudoRequest, clearSecretRequest, clearSudoRequest } from '@/store/prompts'

// Renders the modal mid-turn prompts the gateway raises and waits on: sudo
// password and skill secret capture. Dangerous-command / execute_code approval
// prefers the pending tool row, but also has a chat-level fallback when no row
// is mounted (remote gateway sessions can raise the request before the matching
// tool call is visible). Each Python-side caller blocks the agent thread until
// the matching `*.respond` RPC lands; without a renderer the agent stalls until
// its timeout and the tool is BLOCKED. Any close path (Esc, backdrop
// click) funnels through Radix's single `onOpenChange(false)` and maps to a
// refusal, so silence is never mistaken for consent, matching the TUI. We
// deliberately do NOT add onEscapeKeyDown / onInteractOutside handlers — they'd
// fire a second `*.respond` alongside onOpenChange (double-send) or block the
// backdrop-dismiss path.

function SudoDialog() {
  const { t } = useI18n()
  const copy = t.prompts
  const request = useStore($sudoRequest)
  const gateway = useStore($gateway)
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  useEffect(() => {
    setPassword('')
    setSubmitting(false)
    submittingRef.current = false
  }, [request?.requestId])

  const send = useCallback(
    async (value: string) => {
      if (!request || submittingRef.current) {
        return
      }

      if (!gateway) {
        notifyError(new Error(copy.gatewayDisconnected), copy.sudoSendFailed)

        return
      }

      submittingRef.current = true
      setSubmitting(true)

      try {
        const response = await gateway.request<{ request_id?: string; status?: string }>(
          'sudo.respond',
          ownedPromptResponseParams(request, { password: value })
        )

        if (!promptResponseMatches(response, request.requestId)) {
          throw new Error(copy.sudoSendFailed)
        }

        triggerHaptic('submit')
        clearSudoRequest(request.sessionId, request.requestId)
      } catch (error) {
        notifyError(error, copy.sudoSendFailed)
        submittingRef.current = false
        setSubmitting(false)
      }
    },
    [copy.gatewayDisconnected, copy.sudoSendFailed, gateway, request]
  )

  // Cancel → empty password. The backend treats an empty sudo response as a
  // failed sudo (no command runs), so closing the dialog is a safe refusal.
  const onOpenChange = useCallback(
    (open: boolean) => {
      if (!open && !submitting && request) {
        void send('')
      }
    },
    [request, send, submitting]
  )

  const onSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      void send(password)
    },
    [password, send]
  )

  if (!request) {
    return null
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle icon={Lock}>{copy.sudoTitle}</DialogTitle>
          <DialogDescription>{copy.sudoDesc}</DialogDescription>
        </DialogHeader>

        <form className="grid gap-3" onSubmit={onSubmit}>
          <Input
            autoFocus
            disabled={submitting}
            onChange={event => setPassword(event.target.value)}
            placeholder={copy.sudoPlaceholder}
            type="password"
            value={password}
          />
          <DialogFooter>
            <Button disabled={submitting} onClick={() => void send('')} type="button" variant="ghost">
              {t.common.cancel}
            </Button>
            <Button disabled={submitting} type="submit">
              {submitting ? <Loader2 className="size-3.5 animate-spin" /> : t.common.send}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function SecretDialog() {
  const { t } = useI18n()
  const copy = t.prompts
  const request = useStore($secretRequest)
  const gateway = useStore($gateway)
  const [value, setValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  useEffect(() => {
    setValue('')
    setSubmitting(false)
    submittingRef.current = false
  }, [request?.requestId])

  const send = useCallback(
    async (secret: string) => {
      if (!request || submittingRef.current) {
        return
      }

      if (!gateway) {
        notifyError(new Error(copy.gatewayDisconnected), copy.secretSendFailed)

        return
      }

      submittingRef.current = true
      setSubmitting(true)

      try {
        const response = await gateway.request<{ request_id?: string; status?: string }>(
          'secret.respond',
          ownedPromptResponseParams(request, { value: secret })
        )

        if (!promptResponseMatches(response, request.requestId)) {
          throw new Error(copy.secretSendFailed)
        }

        triggerHaptic('submit')
        clearSecretRequest(request.sessionId, request.requestId)
      } catch (error) {
        notifyError(error, copy.secretSendFailed)
        submittingRef.current = false
        setSubmitting(false)
      }
    },
    [copy.gatewayDisconnected, copy.secretSendFailed, gateway, request]
  )

  const onOpenChange = useCallback(
    (open: boolean) => {
      if (!open && !submitting && request) {
        void send('')
      }
    },
    [request, send, submitting]
  )

  const onSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      void send(value)
    },
    [send, value]
  )

  if (!request) {
    return null
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle icon={KeyRound}>{request.envVar || copy.secretTitle}</DialogTitle>
          <DialogDescription>{request.prompt || copy.secretDesc}</DialogDescription>
        </DialogHeader>

        <form className="grid gap-3" onSubmit={onSubmit}>
          <Input
            autoFocus
            disabled={submitting}
            onChange={event => setValue(event.target.value)}
            placeholder={request.envVar || copy.secretPlaceholder}
            type="password"
            value={value}
          />
          <DialogFooter>
            <Button disabled={submitting} onClick={() => void send('')} type="button" variant="ghost">
              {t.common.cancel}
            </Button>
            <Button disabled={submitting || !value} type="submit">
              {submitting ? <Loader2 className="size-3.5 animate-spin" /> : t.common.send}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ClarifyDialog() {
  const { t } = useI18n()
  const copy = t.assistant.clarify
  const request = useStore($clarifyRequest)
  const gateway = useStore($gateway)
  const [answer, setAnswer] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  useEffect(() => {
    setAnswer('')
    setSubmitting(false)
    submittingRef.current = false
  }, [request?.requestId])

  const send = useCallback(
    async (value: string) => {
      if (!request || submittingRef.current) {
        return
      }

      if (!gateway) {
        notifyError(new Error(copy.gatewayDisconnected), copy.sendFailed)

        return
      }

      submittingRef.current = true
      setSubmitting(true)

      try {
        const response = await gateway.request<{ request_id?: string; status?: string }>(
          'clarify.respond',
          ownedPromptResponseParams(request, { answer: value })
        )

        if (!promptResponseMatches(response, request.requestId)) {
          throw new Error(copy.sendFailed)
        }

        triggerHaptic('submit')
        clearClarifyRequest(request.requestId, request.sessionId)
      } catch (error) {
        notifyError(error, copy.sendFailed)
        submittingRef.current = false
        setSubmitting(false)
      }
    },
    [copy.gatewayDisconnected, copy.sendFailed, gateway, request]
  )

  const onOpenChange = useCallback(
    (open: boolean) => {
      if (!open && !submitting && request) {
        void send('')
      }
    },
    [request, send, submitting]
  )

  const onSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const value = answer.trim()

      if (value) {
        void send(value)
      }
    },
    [answer, send]
  )

  if (!request) {
    return null
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle icon={MessageQuestion}>{request.question}</DialogTitle>
          <DialogDescription>{copy.placeholder}</DialogDescription>
        </DialogHeader>

        <form className="grid gap-3" onSubmit={onSubmit}>
          {request.choices?.map(choice => (
            <Button
              disabled={submitting}
              key={choice}
              onClick={() => void send(choice)}
              type="button"
              variant="outline"
            >
              {choice}
            </Button>
          ))}
          <Input
            autoFocus={!request.choices?.length}
            disabled={submitting}
            onChange={event => setAnswer(event.target.value)}
            placeholder={copy.placeholder}
            value={answer}
          />
          <DialogFooter>
            <Button disabled={submitting} onClick={() => void send('')} type="button" variant="ghost">
              {t.common.cancel}
            </Button>
            <Button disabled={submitting || !answer.trim()} type="submit">
              {submitting ? <Loader2 className="size-3.5 animate-spin" /> : t.common.send}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function PromptOverlays({
  includeApprovalFallback = true,
  includeClarify = false
}: {
  includeApprovalFallback?: boolean
  includeClarify?: boolean
}) {
  return (
    <>
      {includeApprovalFallback && <PendingApprovalFallback />}
      <SudoDialog />
      <SecretDialog />
      {includeClarify && <ClarifyDialog />}
    </>
  )
}
