'use client'

import type { RichFenceProps } from './types'

// Renders a ```chart fence as an inline bar or line chart, drawn as a
// dependency-free SVG. The agent emits a small JSON spec; on any parse issue the
// renderer throws and the registry's RichBoundary falls back to the code block.
//
//   ```chart
//   { "type": "bar", "title": "Weekly runs",
//     "data": [ { "label": "Mon", "value": 12 }, { "label": "Tue", "value": 18 } ] }
//   ```

export type ChartType = 'bar' | 'line'

export interface ChartPoint {
  label: string
  value: number
}

export interface ChartSpec {
  data: ChartPoint[]
  title?: string
  type: ChartType
}

const MAX_POINTS = 16

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

/** Pure parser: returns a validated spec or null. Never throws. */
export function parseChartSpec(code: string): ChartSpec | null {
  const trimmed = code.trim()

  if (!trimmed) {
    return null
  }

  let raw: unknown

  try {
    raw = JSON.parse(trimmed)
  } catch {
    return null
  }

  const record = asRecord(raw)

  if (!record || !Array.isArray(record.data)) {
    return null
  }

  const type: ChartType = record.type === 'line' ? 'line' : 'bar'
  const title = typeof record.title === 'string' && record.title.trim() ? record.title.trim() : undefined

  const data: ChartPoint[] = []

  for (const entry of record.data.slice(0, MAX_POINTS)) {
    const point = asRecord(entry)
    const value = typeof point?.value === 'number' ? point.value : Number(point?.value)

    if (!Number.isFinite(value)) {
      continue
    }

    const label = typeof point?.label === 'string' ? point.label : ''
    data.push({ label, value })
  }

  if (data.length === 0) {
    return null
  }

  return { data, title, type }
}

const W = 320
const H = 148
const PAD_X = 10
const PAD_TOP = 8
const PAD_BOTTOM = 22

export default function ChartRenderer({ code }: RichFenceProps) {
  const spec = parseChartSpec(code)

  if (!spec) {
    throw new Error('invalid chart spec')
  }

  const innerW = W - PAD_X * 2
  const innerH = H - PAD_TOP - PAD_BOTTOM
  const values = spec.data.map(p => p.value)
  const max = Math.max(1, ...values.map(v => Math.max(0, v)))
  const n = spec.data.length
  const baseY = PAD_TOP + innerH

  return (
    <figure className="my-2 rounded-lg border border-border bg-muted/30 p-3" data-slot="aui_chart-card">
      {spec.title && <figcaption className="mb-1.5 text-xs font-medium text-muted-foreground">{spec.title}</figcaption>}
      <svg
        aria-label={spec.title ?? `${spec.type} chart`}
        className="w-full text-violet-500"
        role="img"
        viewBox={`0 0 ${W} ${H}`}
      >
        <line stroke="currentColor" strokeOpacity={0.15} x1={PAD_X} x2={W - PAD_X} y1={baseY} y2={baseY} />
        {spec.type === 'bar'
          ? spec.data.map((point, index) => {
              const slot = innerW / n
              const barW = Math.min(28, slot * 0.62)
              const x = PAD_X + slot * (index + 0.5) - barW / 2
              const barH = (Math.max(0, point.value) / max) * innerH

              return (
                <g key={`${index}:${point.label}`}>
                  <rect
                    fill="currentColor"
                    height={Math.max(1, barH)}
                    rx={2}
                    width={barW}
                    x={x}
                    y={baseY - barH}
                  />
                  {point.label && (
                    <text
                      className="fill-muted-foreground"
                      fontSize={8}
                      textAnchor="middle"
                      x={PAD_X + slot * (index + 0.5)}
                      y={H - 8}
                    >
                      {point.label.slice(0, 6)}
                    </text>
                  )}
                </g>
              )
            })
          : (() => {
              const stepX = n > 1 ? innerW / (n - 1) : 0

              const pointFor = (value: number, index: number) => ({
                x: PAD_X + stepX * index,
                y: baseY - (Math.max(0, value) / max) * innerH
              })

              const pts = spec.data.map((p, i) => pointFor(p.value, i))
              const line = pts.map(p => `${p.x},${p.y}`).join(' ')
              const area = `${PAD_X},${baseY} ${line} ${PAD_X + stepX * (n - 1)},${baseY}`

              return (
                <>
                  <polygon fill="currentColor" fillOpacity={0.14} points={area} />
                  <polyline fill="none" points={line} stroke="currentColor" strokeLinejoin="round" strokeWidth={2} />
                  {pts.map((p, index) => (
                    <circle cx={p.x} cy={p.y} fill="currentColor" key={index} r={2.5} />
                  ))}
                  {spec.data.map((point, index) =>
                    point.label ? (
                      <text
                        className="fill-muted-foreground"
                        fontSize={8}
                        key={`l${index}`}
                        textAnchor="middle"
                        x={PAD_X + stepX * index}
                        y={H - 8}
                      >
                        {point.label.slice(0, 6)}
                      </text>
                    ) : null
                  )}
                </>
              )
            })()}
      </svg>
    </figure>
  )
}
