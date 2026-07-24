import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'

const DESKTOP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const DIST_ASSETS = path.join(DESKTOP_ROOT, 'dist', 'assets')

test('production renderer does not contain an unresolved Rolldown re-export helper', async () => {
  await build({ root: DESKTOP_ROOT, logLevel: 'error' })

  const bundles = fs.readdirSync(DIST_ASSETS).filter(file => file.endsWith('.js'))
  assert.ok(bundles.length > 0, 'production build should emit JavaScript assets')

  const unresolvedHelper = /\b__reExport\$\d+\b/
  for (const bundle of bundles) {
    const contents = fs.readFileSync(path.join(DIST_ASSETS, bundle), 'utf8')
    assert.equal(
      unresolvedHelper.test(contents),
      false,
      `${bundle} contains a Rolldown re-export helper without its declaration`
    )
  }
})
