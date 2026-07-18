import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'
import type { LiveViewState } from '@/store/live-view'

import { LiveViewSurface } from './live-view-pane'

const browserState: LiveViewState = {
  actions: [
    {
      id: 'tool-1',
      startedAt: new Date('2026-07-16T12:00:00Z').getTime(),
      status: 'complete',
      toolName: 'browser_navigate'
    }
  ],
  frameUrl: 'data:image/png;base64,frame',
  kind: 'browser',
  paused: false,
  presentation: 'pip',
  sessionId: 'session-1',
  status: 'running',
  streaming: true,
  target: 'https://example.com',
  updatedAt: Date.now()
}

afterEach(cleanup)

function renderSurface(
  state: LiveViewState,
  overrides: Partial<ComponentProps<typeof LiveViewSurface>> = {},
  initialLocale: 'en' | 'ja' | 'zh' | 'zh-hant' = 'en'
) {
  const props: ComponentProps<typeof LiveViewSurface> = {
    onClose: vi.fn(),
    onDock: vi.fn(),
    onPause: vi.fn(),
    state,
    variant: 'pip',
    ...overrides
  }

  render(
    <I18nProvider configClient={null} initialLocale={initialLocale}>
      <LiveViewSurface {...props} />
    </I18nProvider>
  )

  return props
}

describe('LiveViewSurface', () => {
  it('renders the current visual target, frame, status, and recent action', () => {
    renderSurface(browserState)

    expect(screen.getByRole('region', { name: 'Agent live view' })).toBeTruthy()
    expect(screen.getByText(/Browser/)).toBeTruthy()
    expect(screen.getByText(/· Live/)).toBeTruthy()
    expect(screen.getByText('https://example.com')).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Live browser frame' }).getAttribute('src')).toBe(
      'data:image/png;base64,frame'
    )
    expect(screen.getByText('Opened page')).toBeTruthy()
    expect(within(screen.getByRole('listitem')).getByText('Done').getAttribute('class')).toContain('sr-only')
  })

  it('routes PiP pause, dock, and close controls to their owners', () => {
    const props = renderSurface(browserState)

    fireEvent.click(screen.getByRole('button', { name: 'Pause visual updates' }))
    fireEvent.click(screen.getByRole('button', { name: 'Return to side panel' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close live view' }))

    expect(props.onPause).toHaveBeenCalledWith(true)
    expect(props.onDock).toHaveBeenCalledTimes(1)
    expect(props.onClose).toHaveBeenCalledTimes(1)
  })

  it('shows the paused preview state without hiding the current frame', () => {
    renderSurface({ ...browserState, paused: true, streaming: false })

    expect(screen.getByText(/Browser/)).toBeTruthy()
    expect(screen.getByText(/Paused/)).toBeTruthy()
    expect(screen.getByText('Visual updates paused — the agent is still working')).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Live browser frame' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Resume visual updates' })).toBeTruthy()
  })

  it('derives titles and action labels from the active locale instead of session state', () => {
    renderSurface(browserState, {}, 'ja')

    expect(screen.getByText(/ブラウザー/)).toBeTruthy()
    expect(screen.getByText('ページを開きました')).toBeTruthy()
  })
})
