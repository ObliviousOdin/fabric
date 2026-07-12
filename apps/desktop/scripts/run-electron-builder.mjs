// Resolve electronDist at runtime (#38673, #47917): electron-builder 26.8.x can
// re-unpack a broken Electron.app; reusing the installed dist dodges that.
// npm workspace hoisting is non-deterministic — require.resolve finds electron
// wherever it landed. Dist present → -c.electronDist=<abs>/dist; absent → let
// electron-builder fetch via @electron/get (electronVersion + ELECTRON_MIRROR).

import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'

import { createElectronBuilderConfig, DESKTOP_ROOT, loadDesktopBrand } from './desktop-brand.mjs'

const require = createRequire(import.meta.url)

function electronDistDir() {
  try {
    return path.join(path.dirname(require.resolve('electron/package.json')), 'dist')
  } catch {
    return null
  }
}

function distBinary(dist) {
  if (process.platform === 'darwin') {
    return path.join(dist, 'Electron.app', 'Contents', 'MacOS', 'Electron')
  }
  if (process.platform === 'win32') {
    return path.join(dist, 'electron.exe')
  }
  return path.join(dist, 'electron')
}

function electronBuilderCli() {
  const pkgJson = require.resolve('electron-builder/package.json')
  const bin = require(pkgJson).bin
  const rel = typeof bin === 'string' ? bin : bin['electron-builder']
  return path.join(path.dirname(pkgJson), rel)
}

const dist = electronDistDir()
const args = []
if (dist && fs.existsSync(distBinary(dist))) {
  args.push(`-c.electronDist=${dist}`)
} else {
  console.warn(
    '[run-electron-builder] no local electron dist; electron-builder will fetch ' +
      'via @electron/get (electronVersion + ELECTRON_MIRROR).'
  )
}

const forwardedArgs = process.argv.slice(2)
if (
  forwardedArgs.some(arg => arg === '-c' || arg === '--config' || arg.startsWith('-c=') || arg.startsWith('--config='))
) {
  console.error('[run-electron-builder] external config files are disabled; use -c.<key>=<value> for a narrow override')
  process.exit(2)
}

// The checked-in package.json holds only non-brand packaging mechanics. At
// build time we validate branding/fabric.json, merge its identity metadata into
// those mechanics, and hand electron-builder one generated config. This keeps
// macOS, Windows, and Linux metadata on a single product branding contract.
const packageJson = JSON.parse(fs.readFileSync(path.join(DESKTOP_ROOT, 'package.json'), 'utf8'))
const brand = loadDesktopBrand()
const generatedConfig = createElectronBuilderConfig(packageJson.build, brand)
const generatedConfigPath = path.join(DESKTOP_ROOT, 'build', 'electron-builder.generated.json')
fs.mkdirSync(path.dirname(generatedConfigPath), { recursive: true })
fs.writeFileSync(generatedConfigPath, `${JSON.stringify(generatedConfig, null, 2)}\n`, 'utf8')

console.log(
  `[run-electron-builder] ${brand.desktopName} (${brand.appId}); protocols=${brand.protocols
    .map(protocol => protocol.scheme)
    .join(',')}`
)
args.push('--config', generatedConfigPath, ...forwardedArgs)

const result = spawnSync(process.execPath, [electronBuilderCli(), ...args], {
  stdio: 'inherit'
})
if (result.error) {
  console.error(`[run-electron-builder] spawn failed: ${result.error.message}`)
  process.exit(1)
}
process.exit(result.status == null ? 1 : result.status)
