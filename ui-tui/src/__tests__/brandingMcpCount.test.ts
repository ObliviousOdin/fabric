import { PassThrough } from 'stream'

import { renderSync } from '@fabric/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

import { fabricMark, logo } from '../banner.js'
import { Banner, SessionPanel } from '../components/branding.js'
import { DEFAULT_THEME } from '../theme.js'
import type { McpServerStatus, SessionInfo } from '../types.js'

// Invariant under test: the TUI banner's MCP headline counts *connected*
// servers, never configured-but-disabled ones. This mirrors the classic CLI
// banner (`mcp_connected = sum(1 for s in mcp_status if s["connected"])` in
// fabric_cli/banner.py) and the "connected" label on the MCP collapse toggle.
//
// Regression: branding.tsx used the raw `info.mcp_servers.length`, so a
// disabled `linear` server alongside a connected `nous-support` server made
// the TUI report "2 MCP" while the classic CLI correctly reported "1 MCP".

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const makeStreams = (columns = 100) => {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()

  Object.assign(stdout, { columns, isTTY: false, rows: 40 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })

  let captured = ''
  stdout.on('data', chunk => {
    captured += chunk.toString()
  })

  return { capture: () => captured, stderr, stdin, stdout }
}

const mcp = (over: Partial<McpServerStatus> & Pick<McpServerStatus, 'name'>): McpServerStatus => ({
  connected: false,
  tools: 0,
  transport: 'http',
  ...over
})

const baseInfo = (mcp_servers: McpServerStatus[]): SessionInfo => ({
  mcp_servers,
  model: 'test-model',
  skills: { core: ['a', 'b'] },
  tools: { file: ['read_file', 'write_file'] }
})

async function renderFooter(info: SessionInfo): Promise<string> {
  const streams = makeStreams()

  const instance = renderSync(React.createElement(SessionPanel, { info, sid: 'test', t: DEFAULT_THEME }), {
    patchConsole: false,
    stderr: streams.stderr as NodeJS.WriteStream,
    stdin: streams.stdin as NodeJS.ReadStream,
    stdout: streams.stdout as NodeJS.WriteStream
  })

  try {
    await delay(20)

    // Strip ANSI so we can assert on the rendered text content.
    // eslint-disable-next-line no-control-regex
    return streams.capture().replace(/\u001b\[[0-9;]*m/g, '')
  } finally {
    instance.unmount()
    instance.cleanup()
  }
}

async function renderBanner(columns: number): Promise<string> {
  const streams = makeStreams(columns)

  const instance = renderSync(React.createElement(Banner, { maxWidth: columns, t: DEFAULT_THEME }), {
    patchConsole: false,
    stderr: streams.stderr as NodeJS.WriteStream,
    stdin: streams.stdin as NodeJS.ReadStream,
    stdout: streams.stdout as NodeJS.WriteStream
  })

  try {
    await delay(20)

    // eslint-disable-next-line no-control-regex
    return streams.capture().replace(/\u001b\[[0-9;]*m/g, '')
  } finally {
    instance.unmount()
    instance.cleanup()
  }
}

describe('Fabric banner branding', () => {
  it('renders the official Fabric mark with the Fabric wordmark at full width', async () => {
    const frame = await renderBanner(100)

    expect(frame).toContain('───fabric')
    expect(frame).toContain('╰──────────╮')
    expect(frame).toContain('Fabric · agentic operations engine')
    expect(frame).not.toContain('█')
    expect(frame).not.toMatch(/Hermes|Nous Research/i)
  })

  it('maps the built-in lockups and semantic skin art to theme colors', () => {
    const full = logo(DEFAULT_THEME.color)
    const mark = fabricMark(DEFAULT_THEME.color)

    const semantic = logo(
      DEFAULT_THEME.color,
      '[bold {accent}]──fabric[/]\n[dim {muted}]╰───╮[/]'
    )

    expect(full.map(([color]) => color)).toEqual([
      DEFAULT_THEME.color.primary,
      DEFAULT_THEME.color.accent,
      DEFAULT_THEME.color.primary,
      DEFAULT_THEME.color.muted
    ])
    expect(mark.map(([, text]) => text).join('\n')).toContain('──f')
    expect(semantic).toEqual([
      [DEFAULT_THEME.color.accent, '──fabric'],
      [DEFAULT_THEME.color.muted, '╰───╮']
    ])
  })

  it('preserves literal Rich colors in custom skin art', () => {
    expect(logo(DEFAULT_THEME.color, '[bold #AABBCC]custom[/]')).toEqual([['#AABBCC', 'custom']])
  })

  it('keeps compact widths legible and Fabric-branded', async () => {
    const frame = await renderBanner(50)

    expect(frame).toContain('Fabric')
    expect(frame).toContain('agentic operations engine')
    expect(frame).not.toMatch(/Hermes|Nous Research/i)
  })

  it('uses Fabric as the session vendor and Fabric for the update fallback', async () => {
    const frame = await renderFooter({ ...baseInfo([]), update_behind: 1, update_command: '' })

    expect(frame).toContain('test-model')
    expect(frame).toContain('Fabric')
    expect(frame).toContain('fabric update')
    expect(frame).not.toMatch(/Hermes|Nous Research/i)
  })
})

describe('branding MCP headline count', () => {
  it('counts only connected servers, not configured-but-disabled ones', async () => {
    const frame = await renderFooter(
      baseInfo([
        mcp({ connected: true, name: 'nous-support', status: 'connected', tools: 6 }),
        mcp({ connected: false, disabled: true, name: 'linear', status: 'disabled' })
      ])
    )

    // One connected server → "1 MCP", never "2 MCP".
    expect(frame).toContain('1 MCP')
    expect(frame).not.toContain('2 MCP')
  })

  it('drops the MCP segment entirely when no server is connected', async () => {
    const frame = await renderFooter(
      baseInfo([mcp({ connected: false, disabled: true, name: 'linear', status: 'disabled' })])
    )

    // Matches the classic CLI, which only appends "· N MCP" when N > 0.
    expect(frame).not.toContain('MCP servers')
    expect(frame).not.toMatch(/\d MCP\b/)
  })

  it('counts every connected server when several are connected', async () => {
    const frame = await renderFooter(
      baseInfo([
        mcp({ connected: true, name: 'alpha', status: 'connected' }),
        mcp({ connected: true, name: 'beta', status: 'connected' }),
        mcp({ connected: false, disabled: true, name: 'gamma', status: 'disabled' })
      ])
    )

    expect(frame).toContain('2 MCP')
    expect(frame).not.toContain('3 MCP')
  })
})
