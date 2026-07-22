import { useStore } from '@nanostores/react'
import { useEffect } from 'react'

import type { SetTitlebarToolGroup, TitlebarTool } from '@/app/shell/titlebar-controls'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import { type Translations, useI18n } from '@/i18n'
import { cn } from '@/lib/utils'
import {
  $liveViews,
  $liveViewStreamFrame,
  hideLiveView,
  type LiveViewAction,
  type LiveViewState,
  popOutLiveView,
  setLiveViewPaused
} from '@/store/live-view'

interface LiveViewSurfaceProps {
  onClose: () => void
  onDock?: () => void
  onPause: (paused: boolean) => void
  state: LiveViewState
  variant: 'docked' | 'pip'
}

type ActionLabelKey = keyof Translations['liveView']['actionLabels']

const ACTION_LABEL_KEYS: Partial<Record<string, ActionLabelKey>> = {
  browser_back: 'browserBack',
  browser_click: 'browserClick',
  browser_console: 'browserConsole',
  browser_forward: 'browserForward',
  browser_get_images: 'browserGetImages',
  browser_navigate: 'browserNavigate',
  browser_press: 'browserPress',
  browser_scroll: 'browserScroll',
  browser_snapshot: 'browserSnapshot',
  browser_type: 'browserType',
  browser_vision: 'browserVision',
  computer_use: 'computerUse'
}

function actionLabel(action: LiveViewAction, copy: Translations['liveView']): string {
  const key = ACTION_LABEL_KEYS[action.toolName]

  return key ? copy.actionLabels[key] : action.toolName === 'computer_use' ? copy.desktopAction : copy.browserAction
}

function actionTime(action: LiveViewAction): string {
  return new Date(action.startedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function statusIcon(action: LiveViewAction): string {
  if (action.status === 'running') {
    return 'loading~spin'
  }

  return action.status === 'error' ? 'error' : 'check'
}

function ToolButton({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <Tip label={label}>
      <Button
        aria-label={label}
        className="[-webkit-app-region:no-drag]"
        onClick={onClick}
        size="icon-titlebar"
        type="button"
        variant="ghost"
      >
        <Codicon name={icon} />
      </Button>
    </Tip>
  )
}

export function LiveViewSurface({ onClose, onDock, onPause, state, variant }: LiveViewSurfaceProps) {
  const { t } = useI18n()
  const copy = t.liveView
  const title = state.kind === 'browser' ? copy.browserTitle : copy.desktopTitle
  const live = (state.streaming || state.status === 'running') && !state.paused

  const statusLabel = state.paused
    ? copy.paused
    : state.status === 'error'
      ? copy.failed
      : state.kind === 'browser' && state.streaming
        ? copy.live
        : state.status === 'running'
          ? state.kind === 'desktop'
            ? copy.working
            : copy.live
          : copy.ready

  const visibleActions = state.actions.slice(-10).reverse()

  return (
    <section
      aria-label={copy.title}
      className={cn(
        'flex h-full min-h-0 w-full flex-col overflow-hidden text-foreground',
        variant === 'pip'
          ? 'rounded-xl border border-(--stroke-overlay) bg-(--ui-overlay-surface-background) shadow-overlay'
          : 'bg-(--ui-editor-surface-background)'
      )}
    >
      <header
        className={cn(
          'flex h-(--titlebar-height) min-h-9 shrink-0 items-center gap-2 border-b border-(--ui-stroke-tertiary) bg-(--ui-sidebar-surface-background) px-2.5',
          variant === 'pip' && '[-webkit-app-region:drag]'
        )}
      >
        <Codicon
          className={cn(live ? 'text-(--fabric-ds-semantic-success)' : 'text-(--ui-text-tertiary)')}
          name={live ? 'circle-filled' : state.status === 'error' ? 'error' : 'circle-outline'}
          size="0.62rem"
        />
        <div className="min-w-0 flex-1 truncate text-[0.72rem] font-medium">
          {title} <span className="text-(--ui-text-tertiary)">· {statusLabel}</span>
        </div>
        {variant === 'pip' && (
          <div className="flex shrink-0 items-center gap-0.5">
            <ToolButton
              icon={state.paused ? 'debug-continue' : 'debug-pause'}
              label={state.paused ? copy.resume : copy.pause}
              onClick={() => onPause(!state.paused)}
            />
            {onDock && <ToolButton icon="layout-panel-right" label={copy.dock} onClick={onDock} />}
            <ToolButton icon="close" label={copy.close} onClick={onClose} />
          </div>
        )}
      </header>

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex h-9 shrink-0 items-center gap-2 border-b border-(--ui-stroke-quaternary) px-3 text-[0.69rem]">
          <Codicon
            className="text-(--ui-text-tertiary)"
            name={state.kind === 'browser' ? 'globe' : 'device-desktop'}
            size="0.78rem"
          />
          <span className="min-w-0 flex-1 truncate font-medium">{state.target || copy.waitingTarget}</span>
        </div>

        <div className="relative min-h-44 flex-[3] overflow-hidden bg-(--ui-bg-secondary)">
          {state.frameUrl ? (
            <img
              alt={state.kind === 'browser' ? copy.browserFrame : copy.desktopFrame}
              className="size-full select-none object-contain"
              draggable={false}
              src={state.frameUrl}
            />
          ) : (
            <div className="grid size-full place-items-center p-8 text-center">
              <div className="max-w-56 text-(--ui-text-tertiary)">
                <Codicon
                  className="mb-3 opacity-70"
                  name={state.kind === 'browser' ? 'globe' : 'device-desktop'}
                  size="1.5rem"
                />
                <p className="text-xs font-medium text-foreground/80">{copy.waitingFrame}</p>
                <p className="mt-1 text-[0.68rem] leading-relaxed">{copy.waitingFrameBody}</p>
              </div>
            </div>
          )}

          {state.paused && (
            <div className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-1.5 border-t border-(--ui-stroke-tertiary) bg-background/90 px-3 py-1.5 text-[0.68rem] font-medium backdrop-blur-sm">
              <Codicon name="debug-pause" size="0.7rem" />
              {copy.previewPaused}
            </div>
          )}
        </div>

        <div className="min-h-24 flex-[2] overflow-y-auto border-t border-(--ui-stroke-tertiary)">
          <div className="sticky top-0 z-1 border-b border-(--ui-stroke-quaternary) bg-(--ui-editor-surface-background)/95 px-3 py-2 text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-(--ui-text-tertiary) backdrop-blur-sm">
            {copy.actions}
          </div>
          {visibleActions.length > 0 ? (
            <ol className="divide-y divide-(--ui-stroke-quaternary)">
              {visibleActions.map(action => (
                <li
                  className="grid grid-cols-[4.7rem_0.8rem_minmax(0,1fr)] gap-2 px-3 py-2 text-[0.67rem]"
                  key={action.id}
                >
                  <time className="font-mono text-[0.61rem] text-(--ui-text-tertiary)">{actionTime(action)}</time>
                  <Codicon
                    className={cn(
                      action.status === 'error'
                        ? 'text-destructive'
                        : action.status === 'running'
                          ? 'text-primary'
                          : 'text-(--fabric-ds-semantic-success)'
                    )}
                    name={statusIcon(action)}
                    size="0.68rem"
                  />
                  <span className="sr-only">
                    {action.status === 'running'
                      ? t.assistant.tool.statusRunning
                      : action.status === 'error'
                        ? t.assistant.tool.statusError
                        : t.assistant.tool.statusDone}
                  </span>
                  <div className="min-w-0">
                    <div className="truncate font-medium">{actionLabel(action, copy)}</div>
                    {action.detail && <div className="mt-0.5 truncate text-(--ui-text-tertiary)">{action.detail}</div>}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <div className="px-3 py-5 text-center text-[0.68rem] text-(--ui-text-tertiary)">{copy.noActions}</div>
          )}
        </div>
      </div>
    </section>
  )
}

const TITLEBAR_GROUP_ID = 'live-view'

export function LiveViewPane({
  sessionId,
  setTitlebarToolGroup
}: {
  sessionId: string
  setTitlebarToolGroup?: SetTitlebarToolGroup
}) {
  const { t } = useI18n()
  const views = useStore($liveViews)
  // Subscribe to only THIS session's frame so another session streaming in the
  // background doesn't re-render (and re-decode) this pane every 500 ms (#64).
  const streamFrame = useStore($liveViewStreamFrame(sessionId))
  const storedState = views[sessionId]
  const state = storedState && streamFrame ? { ...storedState, frameUrl: streamFrame } : storedState
  const paused = storedState?.paused

  useEffect(() => {
    if (!setTitlebarToolGroup || paused === undefined) {
      return
    }

    const tools: TitlebarTool[] = [
      {
        active: paused,
        icon: <Codicon name={paused ? 'debug-continue' : 'debug-pause'} />,
        id: `${TITLEBAR_GROUP_ID}-pause`,
        label: paused ? t.liveView.resume : t.liveView.pause,
        onSelect: () => setLiveViewPaused(sessionId, !paused)
      },
      {
        icon: <Codicon name="multiple-windows" />,
        id: `${TITLEBAR_GROUP_ID}-pop-out`,
        label: t.liveView.popOut,
        onSelect: () => void popOutLiveView(sessionId)
      },
      {
        icon: <Codicon name="close" />,
        id: `${TITLEBAR_GROUP_ID}-close`,
        label: t.liveView.close,
        onSelect: () => hideLiveView(sessionId)
      }
    ]

    setTitlebarToolGroup(TITLEBAR_GROUP_ID, tools)

    return () => setTitlebarToolGroup(TITLEBAR_GROUP_ID, [])
  }, [
    sessionId,
    setTitlebarToolGroup,
    paused,
    t.liveView.close,
    t.liveView.pause,
    t.liveView.popOut,
    t.liveView.resume
  ])

  if (!state) {
    return null
  }

  return (
    <LiveViewSurface
      onClose={() => hideLiveView(sessionId)}
      onPause={paused => setLiveViewPaused(sessionId, paused)}
      state={state}
      variant="docked"
    />
  )
}
