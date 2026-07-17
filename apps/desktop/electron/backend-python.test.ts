'use strict'

import assert from 'node:assert/strict'
import test from 'node:test'

import { pythonCandidatesForRoot } from './backend-python'

test('prefers checkout environments before the managed Fabric venv on POSIX', () => {
  assert.deepEqual(pythonCandidatesForRoot('/worktree', '/home/user/.fabric/fabric-agent/venv', 'darwin'), [
    '/worktree/.venv/bin/python',
    '/worktree/venv/bin/python',
    '/home/user/.fabric/fabric-agent/venv/bin/python'
  ])
})

test('deduplicates the managed venv when the active install is the source root', () => {
  assert.deepEqual(
    pythonCandidatesForRoot('/home/user/.fabric/fabric-agent', '/home/user/.fabric/fabric-agent/venv', 'linux'),
    [
      '/home/user/.fabric/fabric-agent/.venv/bin/python',
      '/home/user/.fabric/fabric-agent/venv/bin/python'
    ]
  )
})

test('uses Windows venv executable paths on Windows', () => {
  assert.deepEqual(
    pythonCandidatesForRoot('C:\\worktree', 'C:\\Users\\me\\.fabric\\fabric-agent\\venv', 'win32'),
    [
      'C:\\worktree\\.venv\\Scripts\\python.exe',
      'C:\\worktree\\venv\\Scripts\\python.exe',
      'C:\\Users\\me\\.fabric\\fabric-agent\\venv\\Scripts\\python.exe'
    ]
  )
})
