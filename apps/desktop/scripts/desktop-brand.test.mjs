import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  createElectronBuilderConfig,
  DESKTOP_ROOT,
  loadDesktopBrand,
  toPublicDesktopBrand,
  validateDesktopBrand
} from './desktop-brand.mjs'
import { exeIdentityStrings } from './set-exe-identity.mjs'

const brand = loadDesktopBrand()
const packageJson = JSON.parse(fs.readFileSync(path.join(DESKTOP_ROOT, 'package.json'), 'utf8'))

function mutableBrand() {
  return structuredClone(brand)
}

function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')
}

test('Fabric desktop brand exposes the renderer-safe public contract', () => {
  const publicBrand = toPublicDesktopBrand(brand)

  assert.equal(publicBrand.productName, 'Fabric')
  assert.equal(publicBrand.desktopName, 'Fabric')
  assert.equal(publicBrand.vendorName, 'Fabric')
  assert.equal(publicBrand.supportEmail, '11676741+ObliviousOdin@users.noreply.github.com')
  assert.equal(publicBrand.docsUrl, 'https://obliviousodin.github.io/fabric/')
  assert.equal(publicBrand.websiteUrl, 'https://github.com/ObliviousOdin/fabric/')
  assert.equal(publicBrand.releaseNotesUrl, 'https://github.com/ObliviousOdin/fabric/releases')
  assert.equal(publicBrand.appId, 'io.github.obliviousodin.fabric')
  assert.equal(publicBrand.cliName, 'fabric')
  assert.equal(publicBrand.homeDirectoryName, '.fabric')
  assert.equal(publicBrand.executableName, 'Fabric')
  assert.equal(publicBrand.iconAsset, 'apple-touch-icon.png')
  assert.equal(publicBrand.primaryProtocol, 'fabric')
  assert.deepEqual(publicBrand.legacyProtocols, ['hermes'])
  assert.equal(Object.isFrozen(publicBrand), true)
})

test('the checked-in Fabric manifest can be loaded and validated explicitly', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-desktop-brand-'))
  const manifestPath = path.join(tempRoot, 'fabric.json')
  fs.writeFileSync(manifestPath, JSON.stringify(brand), 'utf8')
  try {
    assert.equal(loadDesktopBrand(manifestPath, { validateAssets: false }).appId, brand.appId)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('manifest validation rejects unsafe identity, URLs, protocols, and asset paths', () => {
  const invalidAppId = mutableBrand()
  invalidAppId.appId = 'Fabric App'
  assert.throws(() => validateDesktopBrand(invalidAppId), /appId/)

  const invalidUrl = mutableBrand()
  invalidUrl.docsUrl = 'http://docs.example.test/'
  assert.throws(() => validateDesktopBrand(invalidUrl), /docsUrl/)

  const noLegacy = mutableBrand()
  noLegacy.protocols = noLegacy.protocols.filter(protocol => !protocol.legacy)
  assert.throws(() => validateDesktopBrand(noLegacy), /legacy/)

  const duplicateProtocol = mutableBrand()
  duplicateProtocol.protocols[1].scheme = duplicateProtocol.protocols[0].scheme
  assert.throws(() => validateDesktopBrand(duplicateProtocol), /duplicated/)

  const escapedAsset = mutableBrand()
  escapedAsset.assets.ico = '../outside.ico'
  assert.throws(() => validateDesktopBrand(escapedAsset), /assets\.ico/)
})

test('Electron Builder metadata is derived consistently for macOS, Windows, and Linux', () => {
  const base = structuredClone(packageJson.build)
  const config = createElectronBuilderConfig(base, brand)

  assert.deepEqual(packageJson.build, base, 'brand generation must not mutate package mechanics')
  assert.equal(config.appId, 'io.github.obliviousodin.fabric')
  assert.equal(config.productName, 'Fabric')
  assert.equal(config.executableName, 'Fabric')
  assert.equal(config.artifactName, 'Fabric-${version}-${os}-${arch}.${ext}')
  assert.equal(config.icon, 'assets/icon')
  assert.deepEqual(config.extraMetadata, {
    productName: 'Fabric',
    desktopName: 'Fabric',
    description: 'Native desktop app for Fabric.',
    homepage: 'https://github.com/ObliviousOdin/fabric/',
    author: { name: 'Fabric', email: '11676741+ObliviousOdin@users.noreply.github.com' }
  })
  assert.deepEqual(config.protocols, [
    { name: 'Fabric Protocol', schemes: ['fabric'] },
    { name: 'Fabric Compatibility Protocol', schemes: ['hermes'] }
  ])

  assert.equal(config.mac.icon, 'assets/icon.icns')
  assert.equal(config.mac.extendInfo.CFBundleDisplayName, 'Fabric')
  assert.equal(config.mac.extendInfo.CFBundleName, 'Fabric')
  assert.equal(config.mac.extendInfo.CFBundleExecutable, 'Fabric')
  assert.equal(config.dmg.title, 'Install Fabric')

  assert.equal(config.win.icon, 'assets/icon.ico')
  assert.equal(config.win.legalTrademarks, 'Fabric')
  assert.equal(config.win.signAndEditExecutable, false)
  assert.equal(config.nsis.shortcutName, 'Fabric')
  assert.equal(config.nsis.uninstallDisplayName, 'Fabric')

  assert.equal(config.linux.icon, 'assets/icon.png')
  assert.equal(config.linux.vendor, 'Fabric')
  assert.equal(config.linux.maintainer, 'Fabric <11676741+ObliviousOdin@users.noreply.github.com>')
  assert.equal(config.linux.syncDesktopName, true)
  assert.equal(config.linux.desktop.entry.Name, 'Fabric')
  assert.equal(config.linux.desktop.entry.StartupWMClass, 'Fabric')
})

test('package metadata delegates native identity to the manifest and excludes legacy artwork', () => {
  assert.equal(packageJson.name, 'fabric-desktop')
  assert.equal(packageJson.productName, brand.productName)
  assert.equal(packageJson.desktopName, brand.desktopName)
  assert.equal(packageJson.description, brand.description)
  assert.equal(packageJson.homepage, brand.websiteUrl)
  for (const key of ['appId', 'productName', 'executableName', 'artifactName', 'protocols', 'icon']) {
    assert.equal(packageJson.build[key], undefined, `package build.${key} must come from the brand manifest`)
  }
  for (const excluded of [
    '!dist/nous-girl.jpg',
    '!dist/hermes.png',
    '!dist/hermes-sprite.png',
    '!dist/hermes-frames/**',
    '!public/nous-girl.jpg',
    '!public/hermes.png',
    '!public/hermes-sprite.png',
    '!public/hermes-frames/**'
  ]) {
    assert.ok(packageJson.build.files.includes(excluded), `${excluded} must be excluded from packages`)
  }
})

test('Windows PE strings and native icon files carry Fabric identity', () => {
  assert.deepEqual(exeIdentityStrings(brand), {
    ProductName: 'Fabric',
    FileDescription: 'Fabric',
    CompanyName: 'Fabric',
    InternalName: 'Fabric',
    OriginalFilename: 'Fabric.exe',
    LegalCopyright: 'Copyright © 2026 Fabric contributors'
  })

  assert.equal(
    sha256(path.join(DESKTOP_ROOT, brand.assets.icns)),
    '65cb2e27be3495eaa650f7b1d5eb6f52df1ab40dc82f04ab510d98cc06900e6a'
  )
  assert.equal(
    sha256(path.join(DESKTOP_ROOT, brand.assets.ico)),
    'e4e50da48100bf0250da499e4511c13759457a6bdd8454a629d1e1413578a00d'
  )
  assert.equal(
    sha256(path.join(DESKTOP_ROOT, brand.assets.png)),
    'e51a099027364620e2758172128ad42dc0a498fee52ab3ec4b2c5197681a39de'
  )
  assert.equal(
    sha256(path.join(DESKTOP_ROOT, brand.assets.publicPng)),
    '5cf6929b5b0b6670595d502e2c67f14e6ac5a8e7cea0f5d3de1390646034b230'
  )
})

test('native shell consumes the manifest for AUMID, About, windows, and dual protocol registration', () => {
  const source = fs.readFileSync(path.join(DESKTOP_ROOT, 'electron', 'main.ts'), 'utf8')

  assert.match(source, /app\.setAppUserModelId\(DESKTOP_BRAND\.appId\)/)
  assert.match(source, /const APP_NAME = DESKTOP_BRAND\.desktopName/)
  assert.match(source, /applicationName: APP_NAME/)
  assert.ok((source.match(/title: APP_NAME/g) || []).length >= 2)
  assert.match(source, /const DESKTOP_PROTOCOLS = Object\.freeze\(DESKTOP_BRAND\.protocols/)
  assert.match(source, /for \(const scheme of DESKTOP_PROTOCOLS\)/)
  assert.match(source, /app\.setAsDefaultProtocolClient\(scheme/)
  assert.equal((source.match(/ipcMain\.handle\('hermes:deep-link-ready'/g) || []).length, 1)
  assert.doesNotMatch(source, /com\.nousresearch\.hermes/)
})
