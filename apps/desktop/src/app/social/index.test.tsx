// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SocialView } from './index'

afterEach(() => {
  cleanup()
})

describe('SocialView composer', () => {
  it('keeps the draft action disabled until the brief has content', () => {
    render(<SocialView onStartSocial={vi.fn()} />)

    const start = screen.getByRole('button', { name: 'Draft in a new chat' })
    expect(start).toHaveProperty('disabled', true)

    fireEvent.change(screen.getByLabelText("What's the post about?"), {
      target: { value: 'We shipped Social Studio after six weeks of work' }
    })

    expect(start).toHaveProperty('disabled', false)
  })

  it('hands a reviewable post prompt to the existing chat flow', () => {
    const onStartSocial = vi.fn()
    render(<SocialView onStartSocial={onStartSocial} />)

    fireEvent.change(screen.getByLabelText("What's the post about?"), {
      target: { value: 'We shipped Social Studio after six weeks of work' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Draft in a new chat' }))

    expect(onStartSocial).toHaveBeenCalledTimes(1)
    const prompt = onStartSocial.mock.calls[0][0].prompt as string
    expect(prompt).toContain('We shipped Social Studio after six weeks of work')
    expect(prompt).toContain('linkedin-post')
  })
})
