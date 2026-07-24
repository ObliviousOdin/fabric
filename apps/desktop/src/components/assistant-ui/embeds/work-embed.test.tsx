import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { RICH_FENCE_LANGUAGES } from './registry'
import WorkRenderer, { parseWorkSpec } from './work-embed'

afterEach(cleanup)

describe('work rich fence — parse', () => {
  it('parses a valid spec with steps', () => {
    const spec = parseWorkSpec('{"title":"Deploy","status":"running","steps":[{"label":"Build","state":"done"}]}')
    expect(spec).not.toBeNull()
    expect(spec?.title).toBe('Deploy')
    expect(spec?.status).toBe('running')
    expect(spec?.steps).toEqual([{ label: 'Build', state: 'done' }])
  })

  it('defaults an unknown status to queued and an unknown step state to pending', () => {
    const spec = parseWorkSpec('{"title":"X","status":"nope","steps":[{"label":"S","state":"wat"}]}')
    expect(spec?.status).toBe('queued')
    expect(spec?.steps[0]?.state).toBe('pending')
  })

  it('drops steps with no label and returns null when the title is missing', () => {
    expect(parseWorkSpec('{"status":"done"}')).toBeNull()
    const spec = parseWorkSpec('{"title":"X","steps":[{"state":"done"},{"label":"Keep"}]}')
    expect(spec?.steps).toEqual([{ label: 'Keep', state: 'pending' }])
  })

  it('returns null for invalid JSON or a blank fence', () => {
    expect(parseWorkSpec('{not json')).toBeNull()
    expect(parseWorkSpec('   ')).toBeNull()
  })
})

describe('work rich fence — render', () => {
  it('is registered alongside the other fence renderers', () => {
    expect(RICH_FENCE_LANGUAGES.has('work')).toBe(true)
  })

  it('renders the title, status, and steps', () => {
    const { container } = render(
      <WorkRenderer code={'{"title":"Deploy staging","status":"running","steps":[{"label":"Build","state":"done"},{"label":"Ship","state":"running"}]}'} />
    )

    expect(container.textContent).toContain('Deploy staging')
    expect(container.textContent).toContain('Running')
    expect(container.textContent).toContain('Build')
    expect(container.textContent).toContain('Ship')
  })

  it('throws on an invalid spec so the boundary can fall back to the code block', () => {
    // React logs the thrown error; that is expected and harmless here.
    expect(() => render(<WorkRenderer code={'{bad'} />)).toThrow()
  })
})
