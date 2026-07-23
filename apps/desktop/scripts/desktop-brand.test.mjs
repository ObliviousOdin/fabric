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
  assert.deepEqual(publicBrand.protocols, [{ scheme: 'fabric', name: 'Fabric Protocol', primary: true }])
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

  const noPrimary = mutableBrand()
  delete noPrimary.protocols[0].primary
  assert.throws(() => validateDesktopBrand(noPrimary), /primary/)

  const duplicateProtocol = mutableBrand()
  duplicateProtocol.protocols.push({ ...duplicateProtocol.protocols[0] })
  assert.throws(() => validateDesktopBrand(duplicateProtocol), /exactly one/)

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
  assert.deepEqual(config.protocols, [{ name: 'Fabric Protocol', schemes: ['fabric'] }])

  assert.equal(config.mac.icon, 'assets/icon.icns')
  assert.equal(config.mac.extendInfo.CFBundleDisplayName, 'Fabric')
  assert.equal(config.mac.extendInfo.CFBundleName, 'Fabric')
  assert.equal(config.mac.extendInfo.CFBundleExecutable, 'Fabric')
  assert.equal(
    config.mac.notarize,
    false,
    'Fabric owns notarization in afterSign so inline .p8 secrets are materialized safely'
  )
  assert.equal(config.afterSign, 'scripts/notarize.mjs')
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

test('package metadata delegates native identity to the manifest and excludes former artwork', () => {
  assert.equal(packageJson.name, 'fabric-desktop')
  assert.equal(packageJson.productName, brand.productName)
  assert.equal(packageJson.desktopName, brand.desktopName)
  assert.equal(packageJson.description, brand.description)
  assert.equal(packageJson.homepage, brand.websiteUrl)
  for (const key of ['appId', 'productName', 'executableName', 'artifactName', 'protocols', 'icon']) {
    assert.equal(packageJson.build[key], undefined, `package build.${key} must come from the brand manifest`)
  }
  const formerIdentity = ['her', 'mes'].join('')
  assert.equal(packageJson.build.files.some(entry => entry.toLowerCase().includes(formerIdentity)), false)
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
    'a96f68ea0dfc250906f52b078b2b5d07b63a999c858e30dc3721d56fc72cb684'
  )
  assert.equal(
    sha256(path.join(DESKTOP_ROOT, brand.assets.ico)),
    '5c00b2f71862baeb2e84f8ea8e1c92bce71ae4cb7cc9b2ba1fe4e0b9ac4ff5db'
  )
  assert.equal(
    sha256(path.join(DESKTOP_ROOT, brand.assets.png)),
    '1a514b79784db3179b2f924dd81bd318cf4cd2605cc24d3fb9d9a43ff6abcfc6'
  )
  assert.equal(
    sha256(path.join(DESKTOP_ROOT, brand.assets.publicPng)),
    'f7f37fdca4e39a731c7e58cfb694b7cc60cb434160a0fc84b9de37532465a8be'
  )
})

test('native shell consumes the manifest for AUMID, About, windows, and protocol registration', () => {
  const source = fs.readFileSync(path.join(DESKTOP_ROOT, 'electron', 'main.ts'), 'utf8')

  assert.match(source, /app\.setAppUserModelId\(DESKTOP_BRAND\.appId\)/)
  assert.match(source, /const APP_NAME = DESKTOP_BRAND\.desktopName/)
  assert.match(source, /applicationName: APP_NAME/)
  assert.ok((source.match(/title: APP_NAME/g) || []).length >= 2)
  assert.match(source, /const DESKTOP_PROTOCOLS = Object\.freeze\(DESKTOP_BRAND\.protocols/)
  assert.match(source, /for \(const scheme of DESKTOP_PROTOCOLS\)/)
  assert.match(source, /app\.setAsDefaultProtocolClient\(scheme/)
  assert.equal((source.match(/ipcMain\.handle\('fabric:deep-link-ready'/g) || []).length, 1)
  assert.equal(source.toLowerCase().includes(['her', 'mes'].join('')), false)
})
