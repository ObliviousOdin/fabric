import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { ErrorBoundary } from '@/components/error-boundary'
import { I18nProvider, useI18n } from '@/i18n'
import type { LiveViewState } from '@/store/live-view'
import { ThemeProvider } from '@/themes/context'

import { LiveViewSurface } from './live-view-pane'

function requestedSessionId(): string {
  return new URLSearchParams(window.location.search).get('session')?.trim() ?? ''
}

function LiveViewWindowApp() {
  const { t } = useI18n()
  const sessionId = requestedSessionId()
  const [state, setState] = useState<LiveViewState | null>(null)

  useEffect(() => {
    const api = window.fabricDesktop?.liveView

    if (!api || !sessionId) {
      return
    }

    const unsubscribe = api.onState(next => {
      if (next?.sessionId === sessionId) {
        setState(next)
      }
    })

    api.control({ sessionId, type: 'ready' })

    const syncVisibility = () => {
      api.control({ sessionId, type: 'visibility', visible: document.visibilityState === 'visible' })
    }

    document.addEventListener('visibilitychange', syncVisibility)
    syncVisibility()

    return () => {
      document.removeEventListener('visibilitychange', syncVisibility)
      unsubscribe()
    }
  }, [sessionId])

  if (!sessionId || !state) {
    return (
      <div className="grid size-full place-items-center bg-(--ui-editor-surface-background) text-xs text-(--ui-text-tertiary)">
        {t.common.connecting}…
      </div>
    )
  }

  return (
    <LiveViewSurface
      onClose={() => window.fabricDesktop.liveView.control({ sessionId, type: 'hide' })}
      onDock={() => window.fabricDesktop.liveView.control({ sessionId, type: 'dock' })}
      onPause={paused => window.fabricDesktop.liveView.control({ paused, sessionId, type: 'pause' })}
      state={state}
      variant="pip"
    />
  )
}

export function mountLiveViewWindow(): void {
  const style = document.createElement('style')
  style.textContent = 'html,body,#root{width:100%;height:100%;overflow:hidden;background:transparent;}'
  document.head.appendChild(style)

  const root = document.getElementById('root')

  if (!root) {
    return
  }

  createRoot(root).render(
    <StrictMode>
      <ErrorBoundary label="live-view-window">
        <I18nProvider>
          <ThemeProvider>
            <LiveViewWindowApp />
          </ThemeProvider>
        </I18nProvider>
      </ErrorBoundary>
    </StrictMode>
  )
}
