import { spawn } from 'node:child_process'

export interface LaunchResult {
  code: null | number
  error?: string
}

export const resolveFabricBin = (env: NodeJS.ProcessEnv = process.env) => env.FABRIC_BIN?.trim() || 'fabric'

export const launchFabricCommand = (args: string[]): Promise<LaunchResult> =>
  new Promise(resolve => {
    const child = spawn(resolveFabricBin(), args, { stdio: 'inherit' })

    child.on('error', err => resolve({ code: null, error: err.message }))
    child.on('exit', code => resolve({ code }))
  })
