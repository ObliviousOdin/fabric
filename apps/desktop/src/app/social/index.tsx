import {
  buildSocialPrompt,
  extractSocialArtifacts,
  SOCIAL_CHANNEL_OPTIONS,
  SOCIAL_FORMAT_OPTIONS,
  SOCIAL_GOAL_OPTIONS,
  SOCIAL_TONE_OPTIONS,
  type SocialArtifact,
  type SocialChannel,
  type SocialFormat,
  type SocialGoal,
  type SocialTone
} from '@fabric/shared'
import type * as React from 'react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { CopyButton } from '@/components/ui/copy-button'
import { Loader } from '@/components/ui/loader'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { getSessionMessages, listAllProfileSessions } from '@/fabric'
import { useI18n } from '@/i18n'
import type { SessionInfo, SessionMessage } from '@/types/fabric'

import { artifactImageSrc, resolveArtifactValue } from '../artifacts/artifact-utils'
import { PAGE_INSET_X } from '../layout-constants'
import { sessionRoute } from '../routes'

export interface SocialStartRequest {
  prompt: string
}

export interface SocialViewProps extends React.ComponentProps<'section'> {
  onStartSocial: (request: SocialStartRequest) => void
}

type Tab = 'compose' | 'library'

const SCAN_LIMIT = 30

/** Map a desktop transcript message onto the shared parser's minimal shape. */
function toSourceMessage(message: SessionMessage) {
  const content =
    typeof message.content === 'string'
      ? message.content
      : typeof message.text === 'string'
        ? message.text
        : null

  return { role: message.role, content, timestamp: message.timestamp }
}

interface SessionArtifacts {
  session: SessionInfo
  artifacts: SocialArtifact[]
}

export function SocialView({ className, onStartSocial, ...props }: SocialViewProps) {
  const { t } = useI18n()
  const s = t.social
  const [tab, setTab] = useState<Tab>('compose')

  return (
    <section
      {...props}
      className={`flex h-full min-w-0 flex-col overflow-y-auto bg-(--ui-chat-surface-background) pt-(--titlebar-height) ${className ?? ''}`}
    >
      <div className={`mx-auto flex w-full max-w-5xl flex-1 flex-col pb-8 pt-8 ${PAGE_INSET_X}`}>
        <header className="border-b border-(--ui-stroke-tertiary) pb-6">
          <div className="mb-3 flex size-8 items-center justify-center rounded-[4px] bg-(--ui-bg-tertiary) text-(--ui-text-secondary)">
            <Codicon name="megaphone" size="1.1rem" />
          </div>
          <h1 className="text-lg font-semibold tracking-[-0.015em] text-(--ui-text-primary)">{s.title}</h1>
          <p className="mt-1.5 max-w-xl text-xs leading-5 text-(--ui-text-secondary)">{s.subtitle}</p>
        </header>

        <div className="pt-6">
          <SegmentedControl
            className="mb-6"
            onChange={setTab}
            options={[
              { id: 'compose', label: s.tabCompose },
              { id: 'library', label: s.tabLibrary }
            ]}
            value={tab}
          />

          {tab === 'compose' ? <SocialComposer onStartSocial={onStartSocial} /> : <SocialLibrary />}
        </div>
      </div>
    </section>
  )
}

function SocialComposer({ onStartSocial }: { onStartSocial: (request: SocialStartRequest) => void }) {
  const { t } = useI18n()
  const s = t.social
  const [brief, setBrief] = useState('')
  const [channel, setChannel] = useState<SocialChannel>('linkedin')
  const [goal, setGoal] = useState<SocialGoal>('authority')
  const [tone, setTone] = useState<SocialTone>('candid')
  const [format, setFormat] = useState<SocialFormat>('hook-story')
  const [includeImage, setIncludeImage] = useState(true)

  const start = () => {
    if (!brief.trim()) {
      return
    }

    onStartSocial({ prompt: buildSocialPrompt({ brief, channel, format, goal, includeImage, tone }) })
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] lg:gap-10">
      <form
        className="min-w-0 space-y-6"
        onSubmit={event => {
          event.preventDefault()
          start()
        }}
      >
        <div>
          <label className="mb-2 block text-xs font-medium text-(--ui-text-primary)" htmlFor="social-brief">
            {s.briefLabel}
          </label>
          <Textarea
            autoFocus
            className="min-h-36 resize-y py-2.5 text-sm leading-5"
            id="social-brief"
            maxLength={2000}
            onChange={event => setBrief(event.target.value)}
            placeholder={s.briefPlaceholder}
            value={brief}
          />
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label className="mb-2 block text-xs font-medium text-(--ui-text-primary)" htmlFor="social-channel">
              {s.channelLabel}
            </label>
            <Select onValueChange={value => setChannel(value as SocialChannel)} value={channel}>
              <SelectTrigger className="w-full" id="social-channel">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SOCIAL_CHANNEL_OPTIONS.map(option => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="mb-2 block text-xs font-medium text-(--ui-text-primary)" htmlFor="social-goal">
              {s.goalLabel}
            </label>
            <Select onValueChange={value => setGoal(value as SocialGoal)} value={goal}>
              <SelectTrigger className="w-full" id="social-goal">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SOCIAL_GOAL_OPTIONS.map(option => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="mb-2 block text-xs font-medium text-(--ui-text-primary)" htmlFor="social-tone">
              {s.toneLabel}
            </label>
            <Select onValueChange={value => setTone(value as SocialTone)} value={tone}>
              <SelectTrigger className="w-full" id="social-tone">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SOCIAL_TONE_OPTIONS.map(option => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="mb-2 block text-xs font-medium text-(--ui-text-primary)" htmlFor="social-format">
              {s.formatLabel}
            </label>
            <Select onValueChange={value => setFormat(value as SocialFormat)} value={format}>
              <SelectTrigger className="w-full" id="social-format">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SOCIAL_FORMAT_OPTIONS.map(option => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <label className="flex cursor-pointer items-start gap-3 rounded-[5px] border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary) p-3">
          <input
            checked={includeImage}
            className="mt-0.5 size-4"
            onChange={event => setIncludeImage(event.target.checked)}
            type="checkbox"
          />
          <span className="min-w-0">
            <span className="block text-xs font-medium text-(--ui-text-primary)">{s.imageLabel}</span>
            <span className="mt-0.5 block text-xs leading-4 text-(--ui-text-secondary)">{s.imageHint}</span>
          </span>
        </label>

        <div className="flex flex-wrap items-center gap-3 border-t border-(--ui-stroke-tertiary) pt-5">
          <Button disabled={!brief.trim()} size="lg" type="submit">
            <Codicon name="wand" />
            {s.start}
          </Button>
          <span className="max-w-sm text-xs leading-4 text-(--ui-text-tertiary)">{s.reviewHint}</span>
        </div>
      </form>

      <aside className="border-t border-(--ui-stroke-tertiary) pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
        <h2 className="text-xs font-semibold text-(--ui-text-primary)">{s.howItWorksTitle}</h2>
        <ol className="mt-5 space-y-4">
          {s.howItWorks.map((step, index) => (
            <li className="grid grid-cols-[1.5rem_minmax(0,1fr)] items-start gap-2" key={step}>
              <span className="font-mono text-xs leading-4 text-(--ui-text-tertiary)">
                {String(index + 1).padStart(2, '0')}
              </span>
              <span className="text-xs leading-4 text-(--ui-text-secondary)">{step}</span>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  )
}

function SocialLibrary() {
  const { t } = useI18n()
  const s = t.social
  const [results, setResults] = useState<SessionArtifacts[] | null>(null)
  const [scanned, setScanned] = useState(0)
  const [error, setError] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const scan = useCallback(async () => {
    setRefreshing(true)
    setError(false)

    try {
      const sessions = (await listAllProfileSessions(SCAN_LIMIT, 1)).sessions

      const settled = await Promise.allSettled(
        sessions.map(session => getSessionMessages(session.id, session.profile))
      )

      const next: SessionArtifacts[] = []

      settled.forEach((outcome, index) => {
        if (outcome.status !== 'fulfilled') {
          return
        }

        const artifacts = extractSocialArtifacts(outcome.value.messages.map(toSourceMessage))

        if (artifacts.length > 0) {
          next.push({ artifacts, session: sessions[index] })
        }
      })

      setResults(next)
      setScanned(sessions.length)
    } catch {
      setError(true)
      setResults([])
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void scan()
  }, [scan])

  if (!results) {
    return <Loader className="mt-10" label={s.scanning} type="lemniscate-bloom" />
  }

  if (error) {
    return (
      <div className="mt-6 space-y-3">
        <p className="text-sm text-(--ui-status-danger-text)">{s.loadFailed}</p>
        <Button onClick={() => void scan()} size="sm" type="button" variant="outline">
          {t.common.retry}
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-(--ui-text-tertiary)">{s.scannedNote(scanned)}</p>
        <Button disabled={refreshing} onClick={() => void scan()} size="sm" type="button" variant="ghost">
          {refreshing ? <Loader className="size-4" label={s.refresh} type="lemniscate-bloom" /> : <Codicon name="refresh" />}
          {s.refresh}
        </Button>
      </div>

      {results.length === 0 ? (
        <div className="grid place-items-center px-6 py-16 text-center">
          <div>
            <div className="text-sm font-medium text-(--ui-text-primary)">{s.emptyTitle}</div>
            <div className="mt-1 text-xs text-(--ui-text-secondary)">{s.emptyBody}</div>
          </div>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {results.map(row => (
            <SocialCard key={row.session.id} row={row} />
          ))}
        </div>
      )}
    </div>
  )
}

function SocialCard({ row }: { row: SessionArtifacts }) {
  const { t } = useI18n()
  const s = t.social
  const navigate = useNavigate()
  const latest = row.artifacts[row.artifacts.length - 1]
  const title = row.session.title?.trim() || row.session.preview?.trim() || s.untitled

  return (
    <article className="flex flex-col overflow-hidden rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-chat-bubble-background)">
      {latest.imagePath ? (
        <SocialImage alt={s.imageAlt} path={latest.imagePath} sessionCwd={row.session.cwd} />
      ) : (
        <div className="flex h-36 items-center justify-center border-b border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) text-(--ui-text-tertiary)">
          <Codicon name="symbol-string" size="1.4rem" />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col gap-2 p-3">
        <div className="truncate text-xs font-medium text-(--ui-text-primary)" title={title}>
          {title}
        </div>
        <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-xs leading-4 text-(--ui-text-secondary)">
          {latest.caption}
        </pre>
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-(--ui-stroke-tertiary) pt-2">
          <span className="text-[0.625rem] uppercase tracking-[0.08em] text-(--ui-text-tertiary)">
            {row.artifacts.length > 1
              ? s.drafts(row.artifacts.length)
              : latest.imagePath
                ? s.withImage
                : s.textOnly}
          </span>
          <div className="flex items-center gap-1.5">
            <Button
              onClick={() => navigate(sessionRoute(row.session.id))}
              size="xs"
              type="button"
              variant="textStrong"
            >
              <Codicon name="comment-discussion" size="0.85rem" />
              {s.openConversation}
            </Button>
            <CopyButton appearance="button" buttonSize="xs" label={s.copyCaption} text={latest.caption} />
          </div>
        </div>
      </div>
    </article>
  )
}

function SocialImage({ alt, path, sessionCwd }: { alt: string; path: string; sessionCwd?: null | string }) {
  const [src, setSrc] = useState('')
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true

    setSrc('')
    setFailed(false)
    const resolved = resolveArtifactValue(path, sessionCwd)

    if (!resolved) {
      setFailed(true)

      return
    }

    void artifactImageSrc(resolved)
      .then(nextSrc => {
        if (active) {
          setSrc(nextSrc)
        }
      })
      .catch(() => {
        if (active) {
          setFailed(true)
        }
      })

    return () => {
      active = false
    }
  }, [path, sessionCwd])

  if (failed) {
    return (
      <div className="flex h-36 flex-col items-center justify-center gap-1 border-b border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) px-3 text-center text-(--ui-text-tertiary)">
        <Codicon name="file-media" size="1.2rem" />
      </div>
    )
  }

  return (
    <div className="flex h-36 items-center justify-center overflow-hidden border-b border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary)">
      {src ? (
        <img alt={alt} className="max-h-36 max-w-full object-contain" onError={() => setFailed(true)} src={src} />
      ) : null}
    </div>
  )
}
