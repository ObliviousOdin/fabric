import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Check, Link, Loader2, RefreshCw, Send, Terminal, Trash2 } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'

import { useGatewayRequest } from '../gateway/hooks/use-gateway-request'

import { ListRow, Pill, SectionHeading, SettingsContent } from './primitives'

interface LinkControllerProfile {
  grants: string[]
  id: string
  label: string
  machine_fingerprint: string
  platform: string
  relay: string
  status: 'active' | 'pending'
}

interface EnrollmentStart {
  controller_id: string
  expires_at: number
  label: string
  machine_fingerprint: string
  relay_origin: string
  short_auth_string: string
}

interface LiveSession {
  id: string
  preview?: string
  status?: string
  title?: string
}

interface RemoteStatus {
  event_seq: number
  generation: null | string
  published: boolean
  session_id: string
}

interface TranscriptMessage {
  role: string
  text: string
}

interface AttachedSession {
  controllerId: string
  controllerLabel: string
  eventSeq: number
  generation: string
  messages: TranscriptMessage[]
  sessionId: string
  title: string
}

interface EventFrame {
  event_seq: number
  frame: {
    params?: {
      payload?: Record<string, unknown>
      type?: string
    }
  }
}

interface EventPage {
  events: EventFrame[]
  high_watermark: number
  snapshot_required: boolean
}

export function nextBoundedEventCursor(current: number, page: Pick<EventPage, 'events' | 'high_watermark'>): number {
  return Math.max(current, page.events.at(-1)?.event_seq ?? page.high_watermark)
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function responseValue<T>(payload: { response: T }): T {
  return payload.response
}

function normalizeMessages(value: unknown): TranscriptMessage[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value.flatMap(item => {
    if (!item || typeof item !== 'object') {
      return []
    }

    const row = item as Record<string, unknown>
    const role = typeof row.role === 'string' ? row.role : 'event'
    const text = typeof row.text === 'string' ? row.text : typeof row.content === 'string' ? row.content : ''

    return text ? [{ role, text }] : []
  })
}

function applyEvents(messages: TranscriptMessage[], events: EventFrame[]): TranscriptMessage[] {
  const next = [...messages]

  for (const event of events) {
    const type = event.frame.params?.type ?? 'event'
    const payload = event.frame.params?.payload ?? {}

    const text =
      typeof payload.text === 'string'
        ? payload.text
        : typeof payload.content === 'string'
          ? payload.content
          : typeof payload.message === 'string'
            ? payload.message
            : ''

    if (!text) {
      continue
    }

    if (type === 'message.delta' && next.at(-1)?.role === 'assistant-live') {
      const previous = next.at(-1)
      next[next.length - 1] = { role: 'assistant-live', text: `${previous?.text ?? ''}${text}` }
    } else {
      next.push({ role: type === 'message.delta' ? 'assistant-live' : type, text })
    }
  }

  return next.slice(-200)
}

export function LinkSettings() {
  const { requestGateway } = useGatewayRequest()
  const [controllers, setControllers] = useState<LinkControllerProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pairingURL, setPairingURL] = useState('')
  const [pairingLabel, setPairingLabel] = useState('Fabric Desktop')
  const [pairing, setPairing] = useState(false)
  const [enrollment, setEnrollment] = useState<EnrollmentStart | null>(null)
  const [dispatchController, setDispatchController] = useState<LinkControllerProfile | null>(null)
  const [dispatchPrompt, setDispatchPrompt] = useState('')
  const [dispatchTitle, setDispatchTitle] = useState('Dispatched from Fabric Desktop')
  const [dispatching, setDispatching] = useState(false)
  const [liveController, setLiveController] = useState<LinkControllerProfile | null>(null)
  const [liveSessions, setLiveSessions] = useState<LiveSession[]>([])
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [attached, setAttached] = useState<AttachedSession | null>(null)
  const [remoteInput, setRemoteInput] = useState('')
  const [submittingInput, setSubmittingInput] = useState(false)
  const pollGeneration = useRef(0)

  const invoke = useCallback(
    async <T,>(controllerId: string, method: string, params: Record<string, unknown>, timeoutSeconds = 120) =>
      responseValue(
        await requestGateway<{ response: T }>(
          'link.controller.invoke',
          {
            controller_id: controllerId,
            method,
            params,
            timeout_seconds: timeoutSeconds
          },
          (timeoutSeconds + 10) * 1000
        )
      ),
    [requestGateway]
  )

  const reload = useCallback(async () => {
    setLoading(true)
    setLoadError(null)

    try {
      const result = await requestGateway<{ controllers: LinkControllerProfile[] }>('link.controller.list')
      setControllers(result.controllers)
    } catch (error) {
      setLoadError(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [requestGateway])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(
    () => () => {
      pollGeneration.current += 1
    },
    []
  )

  const beginPairing = async () => {
    setPairing(true)

    try {
      const result = await requestGateway<EnrollmentStart>(
        'link.controller.enrollment.start',
        {
          pairing_url: pairingURL.trim(),
          label: pairingLabel.trim(),
          grants: ['observe', 'chat', 'dispatch']
        },
        60_000
      )

      setEnrollment(result)
    } catch (error) {
      notifyError(error, 'Fabric Link pairing could not start')
    } finally {
      setPairing(false)
    }
  }

  const finishPairing = async () => {
    if (!enrollment) {
      return
    }

    setPairing(true)

    try {
      await requestGateway<LinkControllerProfile>(
        'link.controller.enrollment.finish',
        {
          controller_id: enrollment.controller_id,
          timeout_seconds: Math.max(1, Math.min(300, enrollment.expires_at - Math.floor(Date.now() / 1000)))
        },
        310_000
      )
      setEnrollment(null)
      setPairingURL('')
      notify({ kind: 'success', message: 'Fabric Link machine paired' })
      await reload()
    } catch (error) {
      notifyError(error, 'The host did not complete pairing')
    } finally {
      setPairing(false)
    }
  }

  const forget = async (controller: LinkControllerProfile) => {
    if (
      !window.confirm(
        `Forget ${controller.label} on this Desktop? This removes the local controller key. Revoke this Desktop on the host too if it is still paired.`
      )
    ) {
      return
    }

    try {
      await requestGateway('link.controller.forget', { controller_id: controller.id })

      if (attached?.controllerId === controller.id) {
        pollGeneration.current += 1
        setAttached(null)
      }

      await reload()
    } catch (error) {
      notifyError(error, 'Could not remove the protected controller state')
    }
  }

  const dispatch = async () => {
    if (!dispatchController || !dispatchPrompt.trim()) {
      return
    }

    setDispatching(true)

    try {
      const result = await requestGateway<{ response: unknown }>(
        'link.controller.dispatch',
        {
          controller_id: dispatchController.id,
          prompt: dispatchPrompt.trim(),
          title: dispatchTitle.trim(),
          idempotency_key: crypto.randomUUID(),
          timeout_seconds: 120
        },
        130_000
      )

      notify({
        kind: 'success',
        message: `Work accepted by ${dispatchController.label}: ${JSON.stringify(result.response)}`
      })
      setDispatchPrompt('')
      setDispatchController(null)
    } catch (error) {
      notifyError(error, `Could not dispatch to ${dispatchController.label}`)
    } finally {
      setDispatching(false)
    }
  }

  const loadLiveSessions = async (controller: LinkControllerProfile) => {
    pollGeneration.current += 1
    setAttached(null)
    setLiveController(controller)
    setLiveSessions([])
    setLoadingSessions(true)

    try {
      const active = await invoke<{ sessions?: LiveSession[] }>(controller.id, 'session.active_list', {})
      const published: LiveSession[] = []

      for (const session of active.sessions ?? []) {
        try {
          const status = await invoke<RemoteStatus>(controller.id, 'session.remote_status', {
            session_id: session.id
          })

          if (status.published) {
            published.push(session)
          }
        } catch {
          // A non-published session intentionally rejects remote_status.
        }
      }

      setLiveSessions(published)
    } catch (error) {
      notifyError(error, `Could not load live sessions from ${controller.label}`)
    } finally {
      setLoadingSessions(false)
    }
  }

  const pollAttachedSession = useCallback(
    async (initial: AttachedSession, generation: number) => {
      let cursor = initial.eventSeq

      while (pollGeneration.current === generation) {
        try {
          const page = await invoke<EventPage>(
            initial.controllerId,
            'events.poll',
            { after_event_seq: cursor, limit: 100, wait_ms: 0 },
            30
          )

          if (pollGeneration.current !== generation) {
            return
          }

          if (page.snapshot_required) {
            notify({
              kind: 'warning',
              message: 'Live-session history moved ahead. Reopen the session for a fresh snapshot.'
            })
            setAttached(null)

            return
          }

          cursor = nextBoundedEventCursor(cursor, page)

          if (page.events.length) {
            setAttached(current =>
              current && current.sessionId === initial.sessionId
                ? {
                    ...current,
                    eventSeq: cursor,
                    messages: applyEvents(current.messages, page.events)
                  }
                : current
            )
          }

          await new Promise(resolve => setTimeout(resolve, page.events.length ? 100 : 750))
        } catch (error) {
          if (pollGeneration.current === generation) {
            notifyError(error, 'Live-session event polling stopped')
            setAttached(null)
          }

          return
        }
      }
    },
    [invoke]
  )

  const attachSession = async (session: LiveSession) => {
    if (!liveController) {
      return
    }

    pollGeneration.current += 1
    const generation = pollGeneration.current

    try {
      const result = await invoke<{
        generation: string
        snapshot: { messages?: unknown }
        snapshot_seq: number
      }>(liveController.id, 'session.attach', {
        session_id: session.id,
        controller_id: `desktop:${liveController.id}`
      })

      const state: AttachedSession = {
        controllerId: liveController.id,
        controllerLabel: liveController.label,
        eventSeq: result.snapshot_seq,
        generation: result.generation,
        messages: normalizeMessages(result.snapshot?.messages),
        sessionId: session.id,
        title: session.title || session.preview || session.id
      }

      setAttached(state)
      void pollAttachedSession(state, generation)
    } catch (error) {
      notifyError(error, 'Could not attach to the exact live session')
    }
  }

  const detachSession = async () => {
    const current = attached

    if (!current) {
      return
    }

    pollGeneration.current += 1
    setAttached(null)

    try {
      await invoke(current.controllerId, 'session.detach', {
        session_id: current.sessionId,
        controller_id: `desktop:${current.controllerId}`
      })
    } catch {
      // The local view is already detached; the host also closes stale
      // transports when the controller reconnects or is revoked.
    }
  }

  const submitRemoteInput = async () => {
    const current = attached
    const text = remoteInput.trim()

    if (!current || !text) {
      return
    }

    setSubmittingInput(true)

    try {
      await invoke(current.controllerId, 'session.input.submit', {
        session_id: current.sessionId,
        controller_id: `desktop:${current.controllerId}`,
        request_id: crypto.randomUUID(),
        text
      })
      setRemoteInput('')
    } catch (error) {
      notifyError(error, 'The live session rejected this input')
    } finally {
      setSubmittingInput(false)
    }
  }

  return (
    <SettingsContent>
      <div className="mx-auto max-w-3xl space-y-8 py-6">
        <section>
          <SectionHeading icon={Link} meta="E2EE" title="Fabric Link" />
          <p className="text-xs leading-5 text-(--ui-text-tertiary)">
            Pair this Desktop directly to your Fabric machines with device keys and end-to-end encryption. No GitHub,
            Google, dashboard password, inbound port, or private-network product is used.
          </p>
          {loadError ? (
            <div className="mt-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
              <p>{loadError}</p>
              <p className="mt-1 text-muted-foreground">
                Link controller management requires the local Fabric backend, the native Link core, and your OS
                credential vault.
              </p>
            </div>
          ) : null}
        </section>

        <section className="border-t border-(--ui-stroke-tertiary) pt-5">
          <SectionHeading icon={Link} title="Pair another machine" />
          {enrollment ? (
            <div className="space-y-3 rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-quinary) p-4">
              <div>
                <p className="text-xs font-medium">Compare on both screens before approving</p>
                <p className="mt-2 select-all font-mono text-lg tracking-wide">{enrollment.short_auth_string}</p>
              </div>
              <div className="space-y-1 font-mono text-[0.68rem] text-muted-foreground">
                <p>Machine: {enrollment.machine_fingerprint}</p>
                <p>Relay: {enrollment.relay_origin}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button disabled={pairing} onClick={() => void finishPairing()}>
                  {pairing ? <Loader2 className="animate-spin" /> : <Check />}I compared it — wait for host approval
                </Button>
                <Button disabled={pairing} onClick={() => setEnrollment(null)} variant="text">
                  Cancel locally
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <ListRow
                description="Paste the v3 link printed by `fabric link pair desktop` on the machine you want to control."
                title="One-time pairing link"
                wide
              />
              <Input
                aria-label="Fabric Link pairing URL"
                onChange={event => setPairingURL(event.target.value)}
                placeholder="https://relay.example/link/pair#pair=…"
                value={pairingURL}
              />
              <Input
                aria-label="Controller name"
                maxLength={96}
                onChange={event => setPairingLabel(event.target.value)}
                placeholder="Fabric Desktop"
                value={pairingLabel}
              />
              <Button
                disabled={pairing || !pairingURL.trim() || !pairingLabel.trim()}
                onClick={() => void beginPairing()}
              >
                {pairing ? <Loader2 className="animate-spin" /> : <Link />}
                Start secure pairing
              </Button>
            </div>
          )}
        </section>

        <section className="border-t border-(--ui-stroke-tertiary) pt-5">
          <div className="flex items-center justify-between gap-3">
            <SectionHeading icon={Terminal} meta={String(controllers.length)} title="Paired machines" />
            <Button disabled={loading} onClick={() => void reload()} size="xs" variant="ghost">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
              Refresh
            </Button>
          </div>
          {!loading && controllers.length === 0 ? (
            <p className="py-4 text-xs text-muted-foreground">No machines are paired to this Desktop yet.</p>
          ) : null}
          <div className="divide-y divide-(--ui-stroke-tertiary)">
            {controllers.map(controller => (
              <ListRow
                action={
                  <div className="flex flex-wrap justify-end gap-2">
                    {controller.status === 'active' ? (
                      <>
                        <Button onClick={() => setDispatchController(controller)} size="xs" variant="secondary">
                          <Send />
                          Dispatch
                        </Button>
                        <Button onClick={() => void loadLiveSessions(controller)} size="xs" variant="secondary">
                          <Terminal />
                          Live sessions
                        </Button>
                      </>
                    ) : null}
                    <Button
                      aria-label={`Forget ${controller.label}`}
                      onClick={() => void forget(controller)}
                      size="icon-xs"
                      variant="ghost"
                    >
                      <Trash2 />
                    </Button>
                  </div>
                }
                description={
                  <>
                    {controller.relay} · {controller.machine_fingerprint}
                  </>
                }
                hint={controller.id}
                key={controller.id}
                title={
                  <span className="flex items-center gap-2">
                    {controller.label}
                    <Pill tone={controller.status === 'active' ? 'primary' : 'muted'}>{controller.status}</Pill>
                    <span className="text-[0.68rem] font-normal text-muted-foreground">
                      {controller.grants.join(', ') || 'awaiting approval'}
                    </span>
                  </span>
                }
              />
            ))}
          </div>
        </section>

        {dispatchController ? (
          <section className="space-y-3 border-t border-(--ui-stroke-tertiary) pt-5">
            <SectionHeading icon={Send} title={`Dispatch to ${dispatchController.label}`} />
            <Input
              aria-label="Dispatch title"
              maxLength={200}
              onChange={event => setDispatchTitle(event.target.value)}
              value={dispatchTitle}
            />
            <Textarea
              aria-label="Dispatch prompt"
              className="min-h-28"
              maxLength={200_000}
              onChange={event => setDispatchPrompt(event.target.value)}
              placeholder="Describe the separate durable Work you want this machine to start…"
              value={dispatchPrompt}
            />
            <div className="flex gap-2">
              <Button disabled={dispatching || !dispatchPrompt.trim()} onClick={() => void dispatch()}>
                {dispatching ? <Loader2 className="animate-spin" /> : <Send />}
                Dispatch Work
              </Button>
              <Button disabled={dispatching} onClick={() => setDispatchController(null)} variant="text">
                Cancel
              </Button>
            </div>
          </section>
        ) : null}

        {liveController ? (
          <section className="space-y-3 border-t border-(--ui-stroke-tertiary) pt-5">
            <SectionHeading icon={Terminal} title={`Published on ${liveController.label}`} />
            {loadingSessions ? (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="animate-spin" /> Looking for exact sessions published with /remote…
              </p>
            ) : liveSessions.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No session is published. In the target terminal chat, run <code>/remote</code> first.
              </p>
            ) : (
              <div className="divide-y divide-(--ui-stroke-tertiary)">
                {liveSessions.map(session => (
                  <ListRow
                    action={
                      <Button onClick={() => void attachSession(session)} size="xs" variant="secondary">
                        Attach
                      </Button>
                    }
                    description={session.preview || session.status || session.id}
                    key={session.id}
                    title={session.title || session.id}
                  />
                ))}
              </div>
            )}
          </section>
        ) : null}

        {attached ? (
          <section className="space-y-3 border-t border-(--ui-stroke-tertiary) pt-5">
            <div className="flex items-center justify-between gap-3">
              <SectionHeading icon={Terminal} meta={`via ${attached.controllerLabel}`} title={attached.title} />
              <Button onClick={() => void detachSession()} size="xs" variant="ghost">
                Detach
              </Button>
            </div>
            <div className="max-h-80 space-y-3 overflow-y-auto rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) p-4">
              {attached.messages.map((message, index) => (
                <div key={`${message.role}-${index}`}>
                  <p className="mb-1 text-[0.65rem] font-medium uppercase tracking-wide text-muted-foreground">
                    {message.role.replace('-live', '')}
                  </p>
                  <p className="whitespace-pre-wrap text-xs leading-5">{message.text}</p>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                aria-label="Live session input"
                onChange={event => setRemoteInput(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void submitRemoteInput()
                  }
                }}
                placeholder="Send the next turn into this exact terminal chat…"
                value={remoteInput}
              />
              <Button disabled={submittingInput || !remoteInput.trim()} onClick={() => void submitRemoteInput()}>
                {submittingInput ? <Loader2 className="animate-spin" /> : <Send />}
                Send
              </Button>
            </div>
          </section>
        ) : null}
      </div>
    </SettingsContent>
  )
}
