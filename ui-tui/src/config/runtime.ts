import { consumeTuiLaunchContext, type TuiLaunchContext } from './launchContext.js'

export interface GatewayRuntimeOptions {
  launchContext: TuiLaunchContext
  packageRevision?: string
  python?: string
  sourceRoot?: string
}

type StringRuntimeOption = 'packageRevision' | 'python' | 'sourceRoot'

const RUNTIME_FLAGS: Record<string, StringRuntimeOption> = {
  '--gateway-python': 'python',
  '--package-revision': 'packageRevision',
  '--source-root': 'sourceRoot'
}

export const parseGatewayRuntimeOptions = (argv: readonly string[] = process.argv.slice(2)): GatewayRuntimeOptions => {
  const options: GatewayRuntimeOptions = { launchContext: { version: 1 } }
  let launchContextPath: string | undefined

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index] ?? ''
    const key = RUNTIME_FLAGS[arg]
    const value = argv[index + 1]?.trim()

    if (key && value) {
      options[key] = value
      index += 1
    } else if (arg === '--launch-context' && value) {
      launchContextPath = value
      index += 1
    }
  }

  options.launchContext = consumeTuiLaunchContext(launchContextPath)

  return options
}

export const GATEWAY_RUNTIME_OPTIONS = parseGatewayRuntimeOptions()
export const TUI_LAUNCH_CONTEXT = GATEWAY_RUNTIME_OPTIONS.launchContext
