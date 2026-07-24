import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import ChartRenderer, { parseChartSpec } from './chart-embed'
import { RICH_FENCE_LANGUAGES } from './registry'

afterEach(cleanup)

describe('chart rich fence — parse', () => {
  it('parses a bar spec and keeps finite points', () => {
    const spec = parseChartSpec('{"type":"bar","title":"Runs","data":[{"label":"Mon","value":12},{"label":"Tue","value":18}]}')
    expect(spec?.type).toBe('bar')
    expect(spec?.title).toBe('Runs')
    expect(spec?.data).toHaveLength(2)
  })

  it('defaults an unknown type to bar and coerces numeric strings', () => {
    const spec = parseChartSpec('{"type":"pie","data":[{"label":"A","value":"5"}]}')
    expect(spec?.type).toBe('bar')
    expect(spec?.data[0]?.value).toBe(5)
  })

  it('drops non-finite values and returns null when nothing survives', () => {
    const spec = parseChartSpec('{"data":[{"label":"A","value":3},{"label":"B","value":"nope"}]}')
    expect(spec?.data).toEqual([{ label: 'A', value: 3 }])
    expect(parseChartSpec('{"data":[{"value":"x"}]}')).toBeNull()
  })

  it('returns null for invalid JSON, a blank fence, or a missing data array', () => {
    expect(parseChartSpec('{oops')).toBeNull()
    expect(parseChartSpec('   ')).toBeNull()
    expect(parseChartSpec('{"type":"bar"}')).toBeNull()
  })
})

describe('chart rich fence — render', () => {
  it('is registered alongside the other fence renderers', () => {
    expect(RICH_FENCE_LANGUAGES.has('chart')).toBe(true)
  })

  it('renders bars for a bar chart', () => {
    const { container } = render(<ChartRenderer code={'{"type":"bar","data":[{"label":"Mon","value":12},{"label":"Tue","value":18}]}'} />)
    expect(container.querySelector('svg')).toBeTruthy()
    expect(container.querySelectorAll('rect')).toHaveLength(2)
  })

  it('renders a polyline for a line chart', () => {
    const { container } = render(<ChartRenderer code={'{"type":"line","data":[{"label":"A","value":1},{"label":"B","value":4},{"label":"C","value":2}]}'} />)
    expect(container.querySelector('polyline')).toBeTruthy()
    expect(container.querySelectorAll('circle')).toHaveLength(3)
  })

  it('throws on an invalid spec so the boundary can fall back', () => {
    expect(() => render(<ChartRenderer code={'{bad'} />)).toThrow()
  })
})
