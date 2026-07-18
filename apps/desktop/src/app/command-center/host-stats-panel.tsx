import { useEffect, useMemo, useState } from 'react'

import type { SystemStats } from '@/hermes'

/** How many samples the sparklines retain. */
const HISTORY = 40

type Series = 'cpu' | 'disk' | 'down' | 'gpu' | 'load' | 'mem' | 'up' | 'vram'
type History = Partial<Record<Series, number[]>>

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function fmtRate(bytesPerSec: number | null | undefined): string {
  if (bytesPerSec == null || Number.isNaN(bytesPerSec)) return '—'
  const v = Math.max(0, bytesPerSec)
  if (v < 1024) return `${v.toFixed(0)} B/s`
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(0)} KB/s`
  return `${(v / (1024 * 1024)).toFixed(1)} MB/s`
}

/** Dependency-free fluid sparkline; color comes from `currentColor`. */
function Spark({ values, max, height = 24 }: { height?: number; max?: number; values: number[] }) {
  const { area, line } = useMemo(() => {
    const n = values.length
    const W = 100
    const H = height
    if (n === 0) {
      const mid = H / 2
      return { area: '', line: `M0,${mid} L${W},${mid}` }
    }
    const lo = Math.min(...values)
    const hi = max ?? Math.max(...values, lo + 1)
    const span = Math.max((max ?? hi) - (max != null ? 0 : lo), 1e-6)
    const base = max != null ? 0 : lo
    const pad = 2
    const xAt = (i: number) => (n === 1 ? W : (i / (n - 1)) * W)
    const yAt = (v: number) => H - pad - ((Math.min(Math.max(v, base), base + span) - base) / span) * (H - pad * 2)
    const pts = values.map((v, i) => `${i ? 'L' : 'M'}${xAt(i).toFixed(2)},${yAt(v).toFixed(2)}`)
    const linePath = pts.join(' ')
    return { area: `${linePath} L${W},${H} L0,${H} Z`, line: linePath }
  }, [values, max, height])

  return (
    <svg
      aria-hidden="true"
      className="mt-1 w-full text-(--ui-text-tertiary)"
      height={height}
      preserveAspectRatio="none"
      viewBox={`0 0 100 ${height}`}
      width="100%"
    >
      {area && <path d={area} fill="currentColor" opacity={0.12} />}
      <path
        d={line}
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

function Tile({
  label,
  max,
  sub,
  unit,
  value,
  values
}: {
  label: string
  max?: number
  sub?: string
  unit?: string
  value: string
  values: number[]
}) {
  return (
    <div className="min-w-0">
      <div className="text-[0.625rem] font-medium uppercase tracking-[0.08em] text-(--ui-text-tertiary)">{label}</div>
      <div className="flex items-baseline gap-1 font-mono tabular-nums text-foreground">
        <span className="text-[length:var(--conversation-text-font-size)]">{value}</span>
        {unit && <span className="text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">{unit}</span>}
        {sub && (
          <span
            className="ml-auto min-w-0 truncate text-[length:var(--conversation-caption-font-size)] font-normal text-(--ui-text-tertiary)"
            title={sub}
          >
            {sub}
          </span>
        )}
      </div>
      <Spark max={max} values={values} />
    </div>
  )
}

/**
 * Desktop twin of the web dashboard's Host card: a live device monitor
 * (CPU, memory, disk, load, network throughput, GPU) rendered inside the
 * Command Center's System section. History is derived from the incoming
 * `stats` prop, which the panel's owner refreshes on a poll.
 */
export function HostStatsPanel({ stats }: { stats: SystemStats | null }) {
  const [history, setHistory] = useState<History>({})

  useEffect(() => {
    if (!stats) return
    setHistory(prev => {
      const out: History = { ...prev }
      const add = (key: Series, v: number | null | undefined) => {
        if (typeof v !== 'number' || Number.isNaN(v)) return
        const arr = (prev[key] ?? []).concat(v)
        out[key] = arr.length > HISTORY ? arr.slice(-HISTORY) : arr
      }
      add('cpu', stats.cpu_percent)
      add('mem', stats.memory?.percent)
      add('disk', stats.disk?.percent)
      add('load', stats.load_avg?.[0])
      add('down', stats.net?.recv_per_sec != null ? stats.net.recv_per_sec / (1024 * 1024) : undefined)
      add('up', stats.net?.sent_per_sec != null ? stats.net.sent_per_sec / (1024 * 1024) : undefined)
      const gpu = stats.gpus?.[0]
      add('gpu', gpu?.util_percent)
      add('vram', gpu?.mem_percent ?? undefined)
      return out
    })
  }, [stats])

  if (!stats) return null
  const gpu = stats.gpus?.[0]

  return (
    <div className="rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) p-3">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[0.625rem] font-medium uppercase tracking-[0.08em] text-(--ui-text-tertiary)">
          {stats.hostname || 'Host'}
          {typeof stats.uptime_seconds === 'number' ? ` · up ${Math.floor(stats.uptime_seconds / 3600)}h` : ''}
        </span>
        {stats.psutil && (
          <span className="inline-flex items-center gap-1.5 font-mono text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
            <span aria-hidden="true" className="relative flex size-1.5">
              <span className="absolute inline-flex size-full rounded-full bg-emerald-500/60 motion-safe:animate-ping" />
              <span className="relative inline-flex size-1.5 rounded-full bg-emerald-500" />
            </span>
            live · 2s
          </span>
        )}
      </div>

      {stats.psutil ? (
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          {typeof stats.cpu_percent === 'number' && (
            <Tile
              label="CPU"
              max={100}
              sub={stats.cpu_count ? `${stats.cpu_count}c` : undefined}
              unit="%"
              value={stats.cpu_percent.toFixed(0)}
              values={history.cpu ?? []}
            />
          )}
          {stats.memory && (
            <Tile
              label="Memory"
              max={100}
              sub={`${fmtBytes(stats.memory.used)} / ${fmtBytes(stats.memory.total)}`}
              unit="%"
              value={stats.memory.percent.toFixed(0)}
              values={history.mem ?? []}
            />
          )}
          {stats.disk && (
            <Tile
              label="Disk"
              max={100}
              sub={`${fmtBytes(stats.disk.used)} / ${fmtBytes(stats.disk.total)}`}
              unit="%"
              value={stats.disk.percent.toFixed(0)}
              values={history.disk ?? []}
            />
          )}
          {stats.load_avg && stats.load_avg.length >= 3 && (
            <Tile
              label="Load avg"
              sub={stats.load_avg.map(n => n.toFixed(2)).join(' / ')}
              value={stats.load_avg[0].toFixed(2)}
              values={history.load ?? []}
            />
          )}
          {stats.net && (
            <>
              <Tile label="Net down" value={fmtRate(stats.net.recv_per_sec)} values={history.down ?? []} />
              <Tile label="Net up" value={fmtRate(stats.net.sent_per_sec)} values={history.up ?? []} />
            </>
          )}
          {gpu && (
            <>
              <Tile label="GPU" max={100} sub={gpu.name} unit="%" value={gpu.util_percent.toFixed(0)} values={history.gpu ?? []} />
              {gpu.mem_percent != null && (
                <Tile
                  label="VRAM"
                  max={100}
                  sub={`${fmtBytes(gpu.mem_used)} / ${fmtBytes(gpu.mem_total)}`}
                  unit="%"
                  value={gpu.mem_percent.toFixed(0)}
                  values={history.vram ?? []}
                />
              )}
            </>
          )}
        </div>
      ) : (
        <p className="text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
          Install the psutil extra for CPU / memory / disk / network metrics.
        </p>
      )}
    </div>
  )
}
