// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DesignView } from './index'

afterEach(() => cleanup())

describe('DesignView', () => {
  it('keeps the action disabled until the brief has content', () => {
    render(<DesignView onStartDesign={vi.fn()} />)

    const start = screen.getByRole('button', { name: 'Start in chat' })
    expect(start).toHaveProperty('disabled', true)

    fireEvent.change(screen.getByLabelText('Brief'), {
      target: { value: 'Design a repository onboarding flow' }
    })

    expect(start).toHaveProperty('disabled', false)
  })

  it('hands a reviewable design prompt to the existing chat flow', () => {
    const onStartDesign = vi.fn()
    render(<DesignView onStartDesign={onStartDesign} />)

    fireEvent.change(screen.getByLabelText('Brief'), {
      target: { value: 'Design a repository onboarding flow' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Start in chat' }))

    expect(onStartDesign).toHaveBeenCalledTimes(1)
    expect(onStartDesign.mock.calls[0][0]).toContain('/design Design a repository onboarding flow')
  })
})
