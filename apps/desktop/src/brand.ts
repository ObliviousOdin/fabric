/**
 * Canonical Fabric desktop identity.
 *
 * Packaging injects the checked-in release manifest as
 * `__FABRIC_DESKTOP_BRAND__`. The fallback keeps tests and source-only Vite
 * consumers deterministic when the packaging step is not running.
 * This module is the single rendered product identity contract.
 */
export interface DesktopBrand {
  cliName: string
  desktopName: string
  docsUrl: string
  homeDirectoryName: string
  iconAsset: string
  productName: string
  releaseNotesUrl: string
  supportEmail: string
  vendorName: string
  websiteUrl: string
}

declare const __FABRIC_DESKTOP_BRAND__: DesktopBrand | undefined

const DEFAULT_DESKTOP_BRAND: DesktopBrand = Object.freeze({
  cliName: 'fabric',
  desktopName: 'Fabric',
  docsUrl: 'https://obliviousodin.github.io/fabric/',
  homeDirectoryName: '.fabric',
  iconAsset: 'apple-touch-icon.png',
  productName: 'Fabric',
  releaseNotesUrl: 'https://github.com/ObliviousOdin/fabric/releases',
  supportEmail: '11676741+ObliviousOdin@users.noreply.github.com',
  vendorName: 'Fabric',
  websiteUrl: 'https://github.com/ObliviousOdin/fabric'
})

function compiledDesktopBrand(): DesktopBrand | undefined {
  try {
    return typeof __FABRIC_DESKTOP_BRAND__ === 'undefined' ? undefined : __FABRIC_DESKTOP_BRAND__
  } catch {
    return undefined
  }
}

export const desktopBrand: DesktopBrand = Object.freeze({
  ...DEFAULT_DESKTOP_BRAND,
  ...compiledDesktopBrand()
})
