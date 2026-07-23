import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFile } from 'node:child_process'

function run(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, (error, stdout, stderr) => {
      if (error) {
        reject(
          new Error(
            `${command} ${args.join(' ')} failed: ${stderr?.trim() || stdout?.trim() || error.message}`
          )
        )
        return
      }
      resolve({ stdout, stderr })
    })
  })
}

function inlineKeyLooksValid(value) {
  return value.includes('BEGIN PRIVATE KEY') && value.includes('END PRIVATE KEY')
}

function resolveApiKeyPath(rawValue) {
  const value = String(rawValue || '').trim()
  if (!value) return { keyPath: '', cleanup: () => {} }

  if (fs.existsSync(value)) {
    return { keyPath: value, cleanup: () => {} }
  }

  if (!inlineKeyLooksValid(value)) {
    throw new Error('APPLE_API_KEY must be a file path or inline .p8 key content')
  }

  const tempPath = path.join(os.tmpdir(), `fabric-notary-${Date.now()}-${process.pid}.p8`)
  fs.writeFileSync(tempPath, value, 'utf8')
  return {
    keyPath: tempPath,
    cleanup: () => {
      try {
        fs.rmSync(tempPath, { force: true })
      } catch {
        // Best-effort cleanup.
      }
    }
  }
}

export function resolveNotarizationCredentials(env = process.env) {
  const profile = String(env.APPLE_NOTARY_PROFILE || '').trim()
  if (profile) {
    return { mode: 'profile', profile }
  }

  const keyId = String(env.APPLE_API_KEY_ID || '').trim()
  const issuer = String(env.APPLE_API_ISSUER || '').trim()
  const rawApiKey = String(env.APPLE_API_KEY || '').trim()
  const configured = [rawApiKey, keyId, issuer].filter(Boolean).length
  const required = String(env.FABRIC_REQUIRE_NOTARIZATION || '').trim().toLowerCase() === 'true'

  if (configured === 3) {
    return { mode: 'api-key', keyId, issuer, rawApiKey }
  }
  if (configured > 0 || required) {
    throw new Error(
      'Notarization requires APPLE_API_KEY, APPLE_API_KEY_ID, and APPLE_API_ISSUER to be configured together.'
    )
  }

  return { mode: 'skip' }
}

export default async function notarize(context) {
  const { electronPlatformName, appOutDir, packager } = context
  if (electronPlatformName !== 'darwin') return

  const appName = packager.appInfo.productFilename
  const appPath = path.join(appOutDir, `${appName}.app`)
  if (!fs.existsSync(appPath)) {
    throw new Error(`Cannot notarize missing app bundle: ${appPath}`)
  }

  const credentials = resolveNotarizationCredentials()
  if (credentials.mode === 'profile') {
    const zipPath = path.join(appOutDir, `${appName}.zip`)
    await run('ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', appPath, zipPath])
    await run('xcrun', ['notarytool', 'submit', zipPath, '--keychain-profile', credentials.profile, '--wait'])
    await run('xcrun', ['stapler', 'staple', '-v', appPath])
    try {
      fs.rmSync(zipPath, { force: true })
    } catch {
      // Best-effort cleanup.
    }
    return
  }

  if (credentials.mode === 'skip') {
    console.log(
      'Skipping notarization: APPLE_API_KEY, APPLE_API_KEY_ID, and APPLE_API_ISSUER are not fully configured.'
    )
    return
  }

  const { keyId, issuer, rawApiKey } = credentials
  const { keyPath, cleanup } = resolveApiKeyPath(rawApiKey)
  const zipPath = path.join(appOutDir, `${appName}.zip`)
  try {
    await run('ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', appPath, zipPath])
    await run('xcrun', ['notarytool', 'submit', zipPath, '--key', keyPath, '--key-id', keyId, '--issuer', issuer, '--wait'])
    await run('xcrun', ['stapler', 'staple', '-v', appPath])
  } finally {
    try {
      fs.rmSync(zipPath, { force: true })
    } catch {
      // Best-effort cleanup.
    }
    cleanup()
  }
}
