'use client'

import type { RichFenceProps } from './types'

// Renders a ```work fence as an inline job card: a title, an overall status
// chip, and an optional checklist of steps. The agent emits a small JSON spec;
// on any parse/validation issue the renderer throws and the registry's
// RichBoundary falls back to the highlighted code block.
//
//   ```work
//   { "title": "Deploy staging", "status": "running",
//     "steps": [ { "label": "Build", "state": "done" },
//                { "label": "Deploy", "state": "running" } ] }
//   ```

export type WorkStatus = 'blocked' | 'done' | 'failed' | 'queued' | 'running'
export type StepState = 'done' | 'failed' | 'pending' | 'running'

export interface WorkStep {
  label: string
  state: StepState
}

export interface WorkSpec {
  status: WorkStatus
  steps: WorkStep[]
  title: string
}

const WORK_STATUSES: ReadonlySet<string> = new Set(['blocked', 'done', 'failed', 'queued', 'running'])
const STEP_STATES: ReadonlySet<string> = new Set(['done', 'failed', 'pending', 'running'])

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

/** Pure parser: returns a validated spec or null. Never throws. */
export function parseWorkSpec(code: string): WorkSpec | null {
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

  if (!record) {
    return null
  }

  const title = typeof record.title === 'string' ? record.title.trim() : ''

  if (!title) {
    return null
  }

  const status: WorkStatus =
    typeof record.status === 'string' && WORK_STATUSES.has(record.status) ? (record.status as WorkStatus) : 'queued'

  const steps: WorkStep[] = []

  if (Array.isArray(record.steps)) {
    for (const entry of record.steps.slice(0, 24)) {
      const stepRecord = asRecord(entry)
      const label = typeof stepRecord?.label === 'string' ? stepRecord.label.trim() : ''

      if (!label) {
        continue
      }

      const state: StepState =
        typeof stepRecord?.state === 'string' && STEP_STATES.has(stepRecord.state)
          ? (stepRecord.state as StepState)
          : 'pending'

      steps.push({ label, state })
    }
  }

  return { status, steps, title }
}

const STATUS_LABEL: Record<WorkStatus, string> = {
  blocked: 'Blocked',
  done: 'Done',
  failed: 'Failed',
  queued: 'Queued',
  running: 'Running'
}

const STATUS_CLASS: Record<WorkStatus, string> = {
  blocked: 'text-amber-600 dark:text-amber-400 bg-amber-500/12',
  done: 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/12',
  failed: 'text-red-600 dark:text-red-400 bg-red-500/12',
  queued: 'text-muted-foreground bg-foreground/8',
  running: 'text-violet-600 dark:text-violet-400 bg-violet-500/12'
}

const STEP_GLYPH: Record<StepState, { className: string; symbol: string }> = {
  done: { className: 'text-emerald-500', symbol: '✓' },
  failed: { className: 'text-red-500', symbol: '✕' },
  pending: { className: 'text-muted-foreground/60', symbol: '○' },
  running: { className: 'text-violet-500', symbol: '◐' }
}

export default function WorkRenderer({ code }: RichFenceProps) {
  const spec = parseWorkSpec(code)

  if (!spec) {
    // Let the registry boundary show the raw fence rather than an empty card.
    throw new Error('invalid work spec')
  }

  return (
    <div className="my-2 rounded-lg border border-border bg-muted/30 p-3 text-sm" data-slot="aui_work-card">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-medium text-foreground">{spec.title}</span>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_CLASS[spec.status]}`}>
          {STATUS_LABEL[spec.status]}
        </span>
      </div>
      {spec.steps.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1">
          {spec.steps.map((step, index) => {
            const glyph = STEP_GLYPH[step.state]

            return (
              <li className="flex items-baseline gap-2 text-[0.8125rem]" key={`${index}:${step.label}`}>
                <span className={`shrink-0 tabular-nums ${glyph.className}`}>{glyph.symbol}</span>
                <span className={step.state === 'done' ? 'text-muted-foreground' : 'text-foreground'}>{step.label}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
