/**
 * after-pack.mjs — electron-builder afterPack hook.
 *
 * 1. Windows: stamps the Fabric icon + identity onto the packed Fabric.exe via
 *    rcedit (delegated to set-exe-identity.mjs). This runs for EVERY packed
 *    build — first install, `fabric desktop`, the installer's --update rebuild,
 *    and a dev's manual `npm run pack` — so the branded exe can never silently
 *    revert to the stock "Electron" icon/name (the bug when the stamp lived
 *    only in install.ps1, which the update path doesn't use).
 *
 * 2. macOS/Linux: re-asserts the +x bit on node-pty's `spawn-helper`. npm
 *    prebuilds and some packers ship it mode 0644; without execute permission
 *    the embedded terminal fails on first open with `posix_spawnp failed`.
 *
 * electron-builder passes a context with:
 *   - electronPlatformName: 'win32' | 'darwin' | 'linux'
 *   - appOutDir:            the unpacked app directory for this target
 *   - packager.appInfo.productFilename: the exe basename (e.g. 'Fabric')
 */

import path from 'node:path'

import { loadDesktopBrand } from './desktop-brand.mjs'
import { ensurePackedNodePtyHelpersExecutable } from './stage-native-deps.mjs'
import { stampExeIdentity } from './set-exe-identity.mjs'

export default async function afterPack(context) {
  const brand = loadDesktopBrand()
  const productName = context.packager?.appInfo?.productFilename || brand.executableName
  // Pass productFilename so macOS (appOutDir parent of Fabric.app) is covered;
  // linux/win use resources/ directly under appOutDir.
  const fixedHelpers = ensurePackedNodePtyHelpersExecutable(context?.appOutDir, {
    productFilename: productName
  })
  if (fixedHelpers.length) {
    console.log(`[after-pack] ensured executable bit on ${fixedHelpers.length} node-pty spawn-helper(s)`)
  }

  if (context.electronPlatformName !== 'win32') {
    return
  }

  const exe = path.join(context.appOutDir, `${productName}.exe`)
  const desktopRoot = path.resolve(import.meta.dirname, '..')

  await stampExeIdentity(exe, desktopRoot, brand)
}
