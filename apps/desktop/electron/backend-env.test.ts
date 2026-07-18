import assert from 'node:assert/strict'
import path from 'node:path'
import test from 'node:test'

import {
  appendUniquePathEntries,
  buildDesktopBackendEnv,
  buildDesktopBackendPath,
  normalizeHermesHomeRoot,
  pathEnvKey,
  POSIX_SANE_PATH_ENTRIES,
  resolveDesktopHome
} from './backend-env'

test('desktop backend PATH adds Hermes-managed bins and missing POSIX sane entries', () => {
  const result = buildDesktopBackendPath({
    hermesHome: '/Users/test/.hermes',
    venvRoot: '/Users/test/.hermes/fabric-agent/venv',
    home: '/Users/test',
    currentPath: '/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin',
    platform: 'darwin',
    pathModule: path.posix
  })

  const entries = result.split(':')
  assert.equal(entries[0], '/Users/test/.hermes/node/bin')
  assert.equal(entries[1], '/Users/test/.hermes/fabric-agent/venv/bin')
  assert.equal(entries[2], '/Users/test/.local/bin')
  assert.ok(entries.includes('/opt/homebrew/bin'), 'Apple Silicon Homebrew bin is added')
  assert.ok(entries.includes('/opt/homebrew/sbin'), 'Apple Silicon Homebrew sbin is added')
  assert.ok(entries.includes('/usr/local/sbin'), 'missing standard sbin is added')

  for (const expected of POSIX_SANE_PATH_ENTRIES) {
    assert.ok(entries.includes(expected), `${expected} should be present`)
  }
})

test('desktop backend PATH preserves first occurrence and avoids duplicates', () => {
  const result = buildDesktopBackendPath({
    hermesHome: '/Users/test/.hermes',
    venvRoot: '/Users/test/.hermes/fabric-agent/venv',
    home: '/Users/test',
    currentPath: '/Users/test/.local/bin:/opt/homebrew/bin:/usr/bin:/opt/homebrew/bin:/bin',
    platform: 'darwin',
    pathModule: path.posix
  })

  const entries = result.split(':')
  assert.equal(entries.filter(entry => entry === '/Users/test/.local/bin').length, 1)
  assert.equal(entries.filter(entry => entry === '/opt/homebrew/bin').length, 1)
  assert.ok(
    entries.indexOf('/opt/homebrew/bin') < entries.indexOf('/opt/homebrew/sbin'),
    'existing Homebrew bin keeps its precedence over appended missing sane entries'
  )
})

test('buildDesktopBackendEnv extends PYTHONPATH and backend PATH together', () => {
  const env = buildDesktopBackendEnv({
    hermesHome: '/Users/test/.hermes',
    pythonPathEntries: ['/repo/fabric-agent'],
    venvRoot: '/Users/test/.hermes/fabric-agent/venv',
    currentEnv: {
      HOME: '/Users/test',
      PATH: '/usr/bin:/bin',
      PYTHONPATH: '/existing/pythonpath'
    },
    platform: 'darwin',
    pathModule: path.posix
  })

  assert.equal(env.PYTHONPATH, '/repo/fabric-agent:/existing/pythonpath')
  assert.equal(env.FABRIC_HOME, '/Users/test/.hermes')
  assert.equal(env.HERMES_HOME, '/Users/test/.hermes')
  assert.ok(
    env.PATH.startsWith(
      '/Users/test/.hermes/node/bin:/Users/test/.hermes/fabric-agent/venv/bin:/Users/test/.local/bin:'
    )
  )
  assert.ok(env.PATH.includes('/opt/homebrew/bin'))
})

test('Finder-style minimal PATH gains the user local bin without duplication', () => {
  const env = buildDesktopBackendEnv({
    hermesHome: '/Users/test/.fabric',
    venvRoot: '/Users/test/.fabric/fabric-agent/venv',
    currentEnv: {
      HOME: '/Users/test',
      PATH: '/usr/bin:/bin:/usr/sbin:/sbin'
    },
    platform: 'darwin',
    pathModule: path.posix
  })

  const entries = env.PATH.split(':')
  assert.equal(entries[2], '/Users/test/.local/bin')
  assert.equal(entries.filter(entry => entry === '/Users/test/.local/bin').length, 1)
})

test('normalizeHermesHomeRoot maps profile homes back to the global Hermes root', () => {
  assert.equal(
    normalizeHermesHomeRoot('/Users/test/.hermes/profiles/oracle', { pathModule: path.posix }),
    '/Users/test/.hermes'
  )
  assert.equal(
    normalizeHermesHomeRoot('C:\\Users\\test\\AppData\\Local\\hermes\\profiles\\oracle', { pathModule: path.win32 }),
    'C:\\Users\\test\\AppData\\Local\\hermes'
  )
  assert.equal(normalizeHermesHomeRoot('/Users/test/.hermes', { pathModule: path.posix }), '/Users/test/.hermes')
})

test('Windows PATH casing and delimiter are preserved without POSIX sane entries', () => {
  const env = buildDesktopBackendEnv({
    hermesHome: 'C:\\Users\\test\\AppData\\Local\\hermes',
    pythonPathEntries: ['C:\\repo\\fabric-agent'],
    venvRoot: 'C:\\Users\\test\\AppData\\Local\\hermes\\fabric-agent\\venv',
    currentEnv: {
      Path: 'C:\\Windows\\System32;C:\\Windows',
      PYTHONPATH: 'C:\\existing\\pythonpath'
    },
    platform: 'win32',
    pathModule: path.win32
  })

  assert.equal(pathEnvKey({ Path: 'x' }, 'win32'), 'Path')
  assert.equal(env.PATH, undefined)
  assert.ok(env.Path.startsWith('C:\\Users\\test\\AppData\\Local\\hermes\\node\\bin;'))
  assert.ok(env.Path.includes('\\venv\\Scripts;'))
  assert.ok(env.Path.includes(';C:\\Windows\\System32;C:\\Windows'))
  assert.equal(env.Path.includes('/opt/homebrew/bin'), false)
})

test('appendUniquePathEntries drops empty entries and keeps first occurrence', () => {
  assert.equal(appendUniquePathEntries([':/a::/b', ['/a', '/c']], { delimiter: ':' }), '/a:/b:/c')
})

test('resolveDesktopHome prefers FABRIC_HOME while preserving HERMES_HOME compatibility', () => {
  assert.equal(
    resolveDesktopHome({
      env: { FABRIC_HOME: '/data/fabric', HERMES_HOME: '/data/hermes' },
      home: '/Users/test',
      platform: 'darwin',
      pathModule: path.posix
    }),
    '/data/fabric'
  )
  assert.equal(
    resolveDesktopHome({
      env: { HERMES_HOME: '/data/hermes/profiles/work' },
      home: '/Users/test',
      platform: 'darwin',
      pathModule: path.posix
    }),
    '/data/hermes'
  )
})

test('resolveDesktopHome uses modern defaults and only falls back for existing legacy data', () => {
  const existing = new Set(['/Users/test/.hermes'])
  assert.equal(
    resolveDesktopHome({
      env: {},
      home: '/Users/test',
      platform: 'darwin',
      directoryExists: candidate => existing.has(candidate),
      pathModule: path.posix
    }),
    '/Users/test/.hermes'
  )
  existing.add('/Users/test/.fabric')
  assert.equal(
    resolveDesktopHome({
      env: {},
      home: '/Users/test',
      platform: 'darwin',
      directoryExists: candidate => existing.has(candidate),
      pathModule: path.posix
    }),
    '/Users/test/.fabric'
  )
})

test('resolveDesktopHome reads live Windows FABRIC_HOME before legacy registry and default', () => {
  const registry = {
    FABRIC_HOME: 'F:\\Fabric\\data',
    HERMES_HOME: 'H:\\Hermes\\data'
  }
  assert.equal(
    resolveDesktopHome({
      env: { LOCALAPPDATA: 'C:\\Users\\test\\AppData\\Local' },
      home: 'C:\\Users\\test',
      platform: 'win32',
      readRegistryValue: key => registry[key],
      pathModule: path.win32
    }),
    'F:\\Fabric\\data'
  )
  delete registry.FABRIC_HOME
  assert.equal(
    resolveDesktopHome({
      env: { LOCALAPPDATA: 'C:\\Users\\test\\AppData\\Local' },
      home: 'C:\\Users\\test',
      platform: 'win32',
      readRegistryValue: key => registry[key],
      pathModule: path.win32
    }),
    'H:\\Hermes\\data'
  )
})

test('resolveDesktopHome uses isolated modern home under desktop test userData', () => {
  assert.equal(
    resolveDesktopHome({
      env: {},
      home: '/Users/test',
      platform: 'darwin',
      userDataOverride: '/tmp/fabric-desktop-test',
      pathModule: path.posix
    }),
    '/tmp/fabric-desktop-test/fabric-home'
  )
})
