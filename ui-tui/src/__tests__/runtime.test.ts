import { existsSync, statSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { normalizeTuiLaunchContext, writeTuiLaunchContext } from '../config/launchContext.js'
import { parseGatewayRuntimeOptions } from '../config/runtime.js'

describe('parseGatewayRuntimeOptions', () => {
  it('parses the launcher-to-gateway runtime contract', () => {
    expect(
      parseGatewayRuntimeOptions([
        '--source-root',
        '/opt/fabric',
        '--gateway-python',
        '/opt/fabric/.venv/bin/python',
        '--package-revision',
        'abc123'
      ])
    ).toEqual({
      launchContext: { version: 1 },
      packageRevision: 'abc123',
      python: '/opt/fabric/.venv/bin/python',
      sourceRoot: '/opt/fabric'
    })
  })

  it('ignores incomplete and unrelated arguments', () => {
    expect(parseGatewayRuntimeOptions(['--unknown', 'value', '--source-root'])).toEqual({
      launchContext: { version: 1 }
    })
  })

  it('consumes an owner-only launch descriptor without exposing its values in argv', () => {
    const path = writeTuiLaunchContext({
      gateway_url: 'ws://127.0.0.1/api/ws?token=secret',
      model: 'nous/test-model',
      toolsets: ['web', 'terminal'],
      version: 1
    })

    if (process.platform !== 'win32') {
      expect(statSync(path).mode & 0o777).toBe(0o600)
    }

    const options = parseGatewayRuntimeOptions(['--launch-context', path])

    expect(options.launchContext).toMatchObject({
      gateway_url: 'ws://127.0.0.1/api/ws?token=secret',
      model: 'nous/test-model',
      toolsets: ['web', 'terminal']
    })
    expect(existsSync(path)).toBe(false)
  })

  it('rejects malformed launch field types', () => {
    expect(() => normalizeTuiLaunchContext({ gateway_url: ['not', 'a', 'string'], version: 1 })).toThrow(
      /gateway_url/
    )
  })
})
