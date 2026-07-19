import { homedir } from 'node:os'
import { join } from 'node:path'

// These flags belong to the direct Node entry point. They are intentionally
// absent from the public Fabric CLI and from the environment/config surface:
// the profiling harness opts in explicitly for the lifetime of one process.
const args = process.argv.slice(2)

const hasFlag = (name: string) => args.includes(name)

const optionValue = (name: string): string | undefined => {
  const inline = args.find(arg => arg.startsWith(`${name}=`))

  if (inline) {
    return inline.slice(name.length + 1)
  }

  const index = args.indexOf(name)
  const next = index >= 0 ? args[index + 1] : undefined

  return next?.startsWith('--') ? undefined : next
}

const requestedPerfLog = optionValue('--tui-perf-log')?.trim()
const requestedThreshold = Number(optionValue('--tui-perf-threshold-ms'))

export const HEAPDUMP_ON_START = hasFlag('--tui-heapdump-on-start')
export const PERF_ENABLED = hasFlag('--tui-perf') || Boolean(requestedPerfLog)
export const PERF_LOG_PATH = requestedPerfLog || join(homedir(), '.fabric', 'perf.log')
export const PERF_THRESHOLD_MS = Number.isFinite(requestedThreshold) ? Math.max(0, requestedThreshold) : 2
export const SHOW_FPS = hasFlag('--tui-fps')
