/**
 * after-pack.mjs — electron-builder afterPack hook.
 *
 * Stamps the Fabric icon + identity onto the packed Windows Fabric.exe via
 * rcedit (delegated to set-exe-identity.mjs). This runs for EVERY packed build
 * — first install, `Fabric desktop`, the installer's --update rebuild, and a
 * dev's manual `npm run pack` — so the branded exe can never silently revert
 * to the stock "Electron" icon/name (the bug when the stamp lived only in
 * install.ps1, which the update path doesn't use).
 *
 * Windows-only: rcedit edits PE resources, irrelevant on macOS/Linux where the
 * app identity comes from the bundle Info.plist / desktop entry. A stamp
 * failure fails packaging: shipping a stock Electron executable would violate
 * the desktop brand contract and cannot be repaired after signing.
 *
 * electron-builder passes a context with:
 *   - electronPlatformName: 'win32' | 'darwin' | 'linux'
 *   - appOutDir:            the unpacked app directory for this target
 *   - packager.appInfo.productFilename: the exe basename (e.g. 'Fabric')
 */

import path from 'node:path'

import { loadDesktopBrand } from './desktop-brand.mjs'
import { stampExeIdentity } from './set-exe-identity.mjs'

export default async function afterPack(context) {
  if (context.electronPlatformName !== 'win32') {
    return
  }

  const brand = loadDesktopBrand()
  const productName = context.packager?.appInfo?.productFilename || brand.executableName
  const exe = path.join(context.appOutDir, `${productName}.exe`)
  const desktopRoot = path.resolve(import.meta.dirname, '..')

  await stampExeIdentity(exe, desktopRoot, brand)
}
