import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ThreadAmbientView } from './thread-ambient'

afterEach(cleanup)

describe('ThreadAmbientView', () => {
  it('is decorative and painted behind content so it can never obscure the chat', () => {
    const { container } = render(<ThreadAmbientView active={false} />)
    const layer = container.querySelector('[data-slot="aui_thread-ambient"]')

    expect(layer).toBeTruthy()
    expect(layer?.getAttribute('aria-hidden')).toBe('true')
    expect(layer?.className).toContain('pointer-events-none')
    expect(layer?.className).toContain('-z-10')
  })

  it('intensifies and animates when the agent is active, gated by reduced motion', () => {
    const { container } = render(<ThreadAmbientView active />)
    const layer = container.querySelector('[data-slot="aui_thread-ambient"]')
    const blob = layer?.querySelector('div')

    expect(layer?.getAttribute('data-active')).toBe('true')
    expect(blob?.className).toContain('animate-pulse')
    expect(blob?.className).toContain('motion-reduce:animate-none')
  })

  it('stays calm and un-animated when idle', () => {
    const { container } = render(<ThreadAmbientView active={false} />)
    const layer = container.querySelector('[data-slot="aui_thread-ambient"]')
    const blob = layer?.querySelector('div')

    expect(layer?.getAttribute('data-active')).toBe('false')
    expect(blob?.className).not.toContain('animate-pulse')
  })
})
