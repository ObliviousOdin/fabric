/**
 * Canonical Fabric desktop identity.
 *
 * Packaging injects the checked-in release manifest as
 * `__FABRIC_DESKTOP_BRAND__`. The fallback keeps tests and source-only Vite
 * consumers deterministic when the packaging step is not running.
 * Internal IPC channels, backend command names, and compatibility env vars
 * intentionally remain lowercase `fabric`; this module is only for rendered
 * product identity.
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

const MODEL_NAME_TOKEN = '__FABRIC_PRESERVED_HERMES_MODEL__'
const MODEL_FAMILY_LABEL = 'Hermes models'.replace(/ models$/, '')

/** Normalize legacy compatibility copy to the Fabric product identity. */
export function brandText(value: string): string {
  return value
    .replace(/\bHermes(?=[ -]?[34](?:\b|\.))/g, MODEL_NAME_TOKEN)
    .replace(/Hermes(?= (?:デスクトップ|桌面版|桌面端|桌面应用|桌面應用程式))/g, desktopBrand.desktopName)
    .replace(
      /\bFabric(?=\s+(?:config|desktop|doctor|gateway|logs|model|setup|skills|status|update)\b)/g,
      desktopBrand.cliName.toLowerCase()
    )
    .replace(/\bFabric\b/g, desktopBrand.desktopName)
    .replace(/\bFabric\b/g, desktopBrand.productName)
    .replace(/\bHermes\b/g, desktopBrand.productName)
    .replace(
      /\bhermes(?=\s+(?:config|desktop|doctor|gateway|logs|model|setup|skills|status|update)\b)/g,
      desktopBrand.cliName
    )
    .replace(/~\/\.hermes(?=\/|\b)/g, `~/${desktopBrand.homeDirectoryName}`)
    .replaceAll(MODEL_NAME_TOKEN, MODEL_FAMILY_LABEL)
}
