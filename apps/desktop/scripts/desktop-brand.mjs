import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const DESKTOP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const DEFAULT_DESKTOP_BRAND_PATH = path.join(DESKTOP_ROOT, 'branding', 'fabric.json')
const REQUIRED_STRING_FIELDS = Object.freeze([
  'productName',
  'desktopName',
  'vendorName',
  'supportEmail',
  'docsUrl',
  'websiteUrl',
  'releaseNotesUrl',
  'appId',
  'cliName',
  'homeDirectoryName',
  'executableName',
  'artifactName',
  'iconAsset',
  'description',
  'copyright'
])
const REQUIRED_ASSET_FIELDS = Object.freeze(['base', 'png', 'ico', 'icns', 'publicPng'])

function fail(source, message) {
  throw new Error(`Invalid desktop brand manifest (${source}): ${message}`)
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) {
    return value
  }

  Object.freeze(value)
  for (const child of Object.values(value)) {
    deepFreeze(child)
  }

  return value
}

function validateHttpsUrl(value, field, source) {
  let url

  try {
    url = new URL(value)
  } catch {
    fail(source, `${field} must be an absolute HTTPS URL`)
  }

  if (url.protocol !== 'https:' || url.username || url.password) {
    fail(source, `${field} must be an absolute HTTPS URL without credentials`)
  }
}

function validateRelativeAsset(value, field, source) {
  if (
    path.posix.isAbsolute(value) ||
    path.win32.isAbsolute(value) ||
    value.includes('\\') ||
    value.split('/').some(segment => segment === '..' || segment === '')
  ) {
    fail(source, `assets.${field} must be a normalized path inside apps/desktop`)
  }
}

/**
 * Validate and normalize an in-memory desktop brand manifest. This function is
 * intentionally pure: it performs no filesystem or environment reads, which
 * makes the exact build contract reusable by Electron, Vite, and tests.
 */
function validateDesktopBrand(input, { source = '<memory>' } = {}) {
  if (!isPlainObject(input)) {
    fail(source, 'root must be an object')
  }
  if (input.schemaVersion !== 1) {
    fail(source, 'schemaVersion must be 1')
  }

  for (const field of REQUIRED_STRING_FIELDS) {
    if (typeof input[field] !== 'string' || !input[field].trim() || input[field] !== input[field].trim()) {
      fail(source, `${field} must be a non-empty, trimmed string`)
    }
    if (/\r|\n|\0/.test(input[field])) {
      fail(source, `${field} must be a single safe line`)
    }
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.supportEmail)) {
    fail(source, 'supportEmail must be an email address')
  }
  for (const field of ['docsUrl', 'websiteUrl', 'releaseNotesUrl']) {
    validateHttpsUrl(input[field], field, source)
  }
  if (!/^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9-]*){2,}$/.test(input.appId)) {
    fail(source, 'appId must be a lowercase reverse-DNS identifier')
  }
  if (!/^[a-z][a-z0-9-]*$/.test(input.cliName)) {
    fail(source, 'cliName must be a lowercase command name')
  }
  if (!/^\.[a-z][a-z0-9-]*$/.test(input.homeDirectoryName)) {
    fail(source, 'homeDirectoryName must be a hidden directory basename')
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9 ._-]*$/.test(input.executableName)) {
    fail(source, 'executableName contains characters unsafe for a native executable')
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(input.artifactName)) {
    fail(source, 'artifactName must be safe in release filenames')
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*\.png$/.test(input.iconAsset)) {
    fail(source, 'iconAsset must be a renderer-safe PNG basename')
  }

  if (!Array.isArray(input.protocols) || input.protocols.length < 2) {
    fail(source, 'protocols must contain a primary scheme and at least one legacy scheme')
  }
  const schemes = new Set()
  let primaryCount = 0
  let legacyCount = 0
  const protocols = input.protocols.map((protocol, index) => {
    if (!isPlainObject(protocol)) {
      fail(source, `protocols[${index}] must be an object`)
    }
    if (typeof protocol.scheme !== 'string' || !/^[a-z][a-z0-9+.-]*$/.test(protocol.scheme)) {
      fail(source, `protocols[${index}].scheme is invalid`)
    }
    if (schemes.has(protocol.scheme)) {
      fail(source, `protocol scheme ${protocol.scheme} is duplicated`)
    }
    schemes.add(protocol.scheme)
    if (typeof protocol.name !== 'string' || !protocol.name.trim() || /\r|\n|\0/.test(protocol.name)) {
      fail(source, `protocols[${index}].name must be a safe non-empty string`)
    }
    if (protocol.primary === true) primaryCount += 1
    if (protocol.legacy === true) legacyCount += 1
    if (protocol.primary === true && protocol.legacy === true) {
      fail(source, `protocols[${index}] cannot be both primary and legacy`)
    }

    return {
      scheme: protocol.scheme,
      name: protocol.name,
      ...(protocol.primary === true ? { primary: true } : {}),
      ...(protocol.legacy === true ? { legacy: true } : {})
    }
  })
  if (primaryCount !== 1) {
    fail(source, 'protocols must contain exactly one primary scheme')
  }
  if (legacyCount < 1) {
    fail(source, 'protocols must preserve at least one legacy scheme')
  }

  if (!isPlainObject(input.assets)) {
    fail(source, 'assets must be an object')
  }
  const assets = {}
  for (const field of REQUIRED_ASSET_FIELDS) {
    const value = input.assets[field]
    if (typeof value !== 'string' || !value.trim() || value !== value.trim()) {
      fail(source, `assets.${field} must be a non-empty, trimmed string`)
    }
    validateRelativeAsset(value, field, source)
    assets[field] = value
  }
  if (!assets.png.endsWith('.png') || !assets.publicPng.endsWith('.png')) {
    fail(source, 'PNG asset paths must end in .png')
  }
  if (!assets.ico.endsWith('.ico') || !assets.icns.endsWith('.icns')) {
    fail(source, 'native icon paths must use .ico and .icns respectively')
  }

  const normalized = {
    schemaVersion: 1,
    ...Object.fromEntries(REQUIRED_STRING_FIELDS.map(field => [field, input[field]])),
    protocols,
    assets,
    primaryProtocol: protocols.find(protocol => protocol.primary).scheme,
    legacyProtocols: protocols.filter(protocol => protocol.legacy).map(protocol => protocol.scheme)
  }

  return deepFreeze(normalized)
}

function loadDesktopBrand(
  manifestPath = DEFAULT_DESKTOP_BRAND_PATH,
  { validateAssets = true, desktopRoot = DESKTOP_ROOT } = {}
) {
  const resolvedPath = path.resolve(manifestPath)
  let parsed

  try {
    parsed = JSON.parse(fs.readFileSync(resolvedPath, 'utf8'))
  } catch (error) {
    throw new Error(`Unable to read desktop brand manifest ${resolvedPath}: ${error.message}`)
  }

  const brand = validateDesktopBrand(parsed, { source: resolvedPath })

  if (validateAssets) {
    for (const field of ['png', 'ico', 'icns', 'publicPng']) {
      const assetPath = path.resolve(desktopRoot, brand.assets[field])
      if (!fs.existsSync(assetPath) || !fs.statSync(assetPath).isFile()) {
        fail(resolvedPath, `assets.${field} does not resolve to a file: ${assetPath}`)
      }
    }
  }

  return brand
}

function toPublicDesktopBrand(brandInput) {
  const brand = validateDesktopBrand(brandInput, { source: '<public desktop brand>' })

  return deepFreeze({
    productName: brand.productName,
    desktopName: brand.desktopName,
    vendorName: brand.vendorName,
    supportEmail: brand.supportEmail,
    docsUrl: brand.docsUrl,
    websiteUrl: brand.websiteUrl,
    releaseNotesUrl: brand.releaseNotesUrl,
    appId: brand.appId,
    cliName: brand.cliName,
    homeDirectoryName: brand.homeDirectoryName,
    executableName: brand.executableName,
    iconAsset: brand.iconAsset,
    protocols: brand.protocols,
    primaryProtocol: brand.primaryProtocol,
    legacyProtocols: brand.legacyProtocols,
    assets: brand.assets
  })
}

function createElectronBuilderConfig(baseConfig, brandInput) {
  const brand = validateDesktopBrand(brandInput, { source: '<electron-builder desktop brand>' })
  const base = structuredClone(baseConfig || {})
  const protocolConfig = brand.protocols.map(protocol => ({
    name: protocol.name,
    schemes: [protocol.scheme]
  }))

  return {
    ...base,
    appId: brand.appId,
    productName: brand.productName,
    executableName: brand.executableName,
    artifactName: `${brand.artifactName}-\${version}-\${os}-\${arch}.\${ext}`,
    copyright: brand.copyright,
    extraMetadata: {
      ...(base.extraMetadata || {}),
      productName: brand.productName,
      desktopName: brand.desktopName,
      description: brand.description,
      homepage: brand.websiteUrl,
      author: {
        name: brand.vendorName,
        email: brand.supportEmail
      }
    },
    icon: brand.assets.base,
    protocols: protocolConfig,
    mac: {
      ...(base.mac || {}),
      icon: brand.assets.icns,
      extendInfo: {
        ...(base.mac?.extendInfo || {}),
        CFBundleDisplayName: brand.desktopName,
        CFBundleExecutable: brand.executableName,
        CFBundleName: brand.productName,
        NSAudioCaptureUsageDescription: `${brand.desktopName} uses audio capture for voice conversations.`,
        NSMicrophoneUsageDescription: `${brand.desktopName} uses the microphone for voice input and voice conversations.`
      }
    },
    dmg: {
      ...(base.dmg || {}),
      title: `Install ${brand.desktopName}`
    },
    win: {
      ...(base.win || {}),
      icon: brand.assets.ico,
      legalTrademarks: brand.vendorName
    },
    linux: {
      ...(base.linux || {}),
      icon: brand.assets.png,
      maintainer: `${brand.vendorName} <${brand.supportEmail}>`,
      vendor: brand.vendorName,
      synopsis: brand.description,
      description: brand.description,
      syncDesktopName: true,
      desktop: {
        ...(base.linux?.desktop || {}),
        entry: {
          ...(base.linux?.desktop?.entry || {}),
          Name: brand.desktopName,
          Comment: brand.description,
          StartupWMClass: brand.desktopName
        }
      }
    },
    nsis: {
      ...(base.nsis || {}),
      shortcutName: brand.desktopName,
      uninstallDisplayName: brand.desktopName
    }
  }
}

export {
  createElectronBuilderConfig,
  DEFAULT_DESKTOP_BRAND_PATH,
  DESKTOP_ROOT,
  loadDesktopBrand,
  toPublicDesktopBrand,
  validateDesktopBrand
}
