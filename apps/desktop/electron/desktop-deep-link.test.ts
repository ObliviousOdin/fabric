import assert from 'node:assert/strict'
import test from 'node:test'

import { extractDesktopDeepLink, parseDesktopDeepLink } from './desktop-deep-link'

const schemes = ['fabric']

test('the Fabric desktop protocol produces the expected payload', () => {
  const expected = {
    kind: 'blueprint',
    name: 'morning brief',
    params: { time: '08:00' }
  }
  const parsed = parseDesktopDeepLink('fabric://blueprint/morning%20brief?time=08%3A00', schemes)
  assert.deepEqual({ kind: parsed?.kind, name: parsed?.name, params: parsed?.params }, expected)
  assert.equal(parsed?.scheme, 'fabric')
})

test('desktop deep-link extraction accepts configured schemes only', () => {
  assert.equal(
    extractDesktopDeepLink(['Fabric.exe', '--profile=work', 'fabric://blueprint/old'], schemes),
    'fabric://blueprint/old'
  )
  assert.equal(extractDesktopDeepLink(['Fabric.exe', 'https://github.com/ObliviousOdin/fabric/'], schemes), null)
  assert.equal(parseDesktopDeepLink('javascript:alert(1)', schemes), null)
  assert.equal(parseDesktopDeepLink('fabric://blueprint/%E0%A4%A', schemes), null)
})
