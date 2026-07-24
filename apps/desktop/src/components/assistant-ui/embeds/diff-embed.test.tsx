import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import DiffRenderer from './diff-embed'
import { RICH_FENCE_LANGUAGES } from './registry'

afterEach(cleanup)

const SAMPLE_DIFF = ['--- a/x.txt', '+++ b/x.txt', '@@ -1 +1 @@', '-old line', '+new line', ''].join('\n')

describe('diff rich fence', () => {
  it('registers the diff language alongside the existing renderers', () => {
    expect(RICH_FENCE_LANGUAGES.has('diff')).toBe(true)
    expect(RICH_FENCE_LANGUAGES.has('mermaid')).toBe(true)
    expect(RICH_FENCE_LANGUAGES.has('svg')).toBe(true)
  })

  it('renders both the added and removed lines from a unified diff', () => {
    const { container } = render(<DiffRenderer code={SAMPLE_DIFF} />)
    expect(container.textContent).toContain('new line')
    expect(container.textContent).toContain('old line')
  })

  it('renders nothing for a blank fence', () => {
    const { container } = render(<DiffRenderer code={'   \n  '} />)
    expect(container.textContent?.trim()).toBe('')
  })
})
