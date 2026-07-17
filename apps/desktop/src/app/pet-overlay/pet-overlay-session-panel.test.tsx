import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PetOverlaySessionPanel } from './pet-overlay-session-panel'

afterEach(cleanup)

describe('PetOverlaySessionPanel', () => {
  it('shows live state and opens the selected session', () => {
    const onOpenSession = vi.fn()

    render(
      <PetOverlaySessionPanel
        onDock={() => undefined}
        onOpenApp={() => undefined}
        onOpenSession={onOpenSession}
        sessions={[
          {
            id: 'session-1',
            lastActive: Date.now() / 1000,
            model: 'openai/gpt-5.6-sol',
            status: 'working',
            title: 'Improve pet overlay'
          }
        ]}
      />
    )

    expect(screen.getByText('1 live')).toBeTruthy()
    expect(screen.getByText('Running · gpt-5.6-sol')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Open session Improve pet overlay' }))
    expect(onOpenSession).toHaveBeenCalledWith('session-1')
  })
})
