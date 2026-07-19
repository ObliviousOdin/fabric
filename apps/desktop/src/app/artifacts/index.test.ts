import { afterEach, describe, expect, it, vi } from 'vitest'

import { $connection } from '@/store/session'
import type { SessionInfo, SessionMessage } from '@/types/fabric'

import { artifactImageSrc, collectArtifactsForSession } from './artifact-utils'

function makeSession(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    ended_at: null,
    id: 'session-1',
    input_tokens: 0,
    is_active: false,
    last_active: 1000,
    message_count: 1,
    model: null,
    output_tokens: 0,
    preview: null,
    source: null,
    started_at: 1000,
    title: 'Session',
    tool_call_count: 0,
    ...overrides
  }
}

describe('collectArtifactsForSession', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
    $connection.set(null)
  })

  it('indexes plain https links from assistant text', () => {
    const artifacts = collectArtifactsForSession(makeSession(), [
      {
        content: 'Reference: https://example.com/docs/getting-started',
        role: 'assistant',
        timestamp: 2000
      }
    ])

    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]).toMatchObject({
      href: 'https://example.com/docs/getting-started',
      kind: 'link',
      value: 'https://example.com/docs/getting-started'
    })
  })

  it('indexes http links present in tool JSON payloads', () => {
    const messages: SessionMessage[] = [
      {
        content: JSON.stringify({ source_url: 'https://example.com/changelog/latest' }),
        role: 'tool',
        timestamp: 3000
      }
    ]

    const artifacts = collectArtifactsForSession(makeSession({ id: 'session-2' }), messages)

    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]).toMatchObject({
      href: 'https://example.com/changelog/latest',
      kind: 'link',
      value: 'https://example.com/changelog/latest'
    })
  })

  it('indexes design files from tool payloads and resolves them against the session workspace', () => {
    const artifacts = collectArtifactsForSession(makeSession({ cwd: '/work/product' }), [
      {
        content: JSON.stringify({ path: 'artifacts/Design System Board.html' }),
        role: 'tool',
        timestamp: 4000
      },
      {
        content: 'Created `DESIGN.md` and `artifacts/tokens.json`.',
        role: 'assistant',
        timestamp: 5000
      }
    ])

    expect(artifacts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          href: 'file:///work/product/artifacts/Design System Board.html',
          kind: 'file',
          value: '/work/product/artifacts/Design System Board.html'
        }),
        expect.objectContaining({
          href: 'file:///work/product/DESIGN.md',
          kind: 'file',
          value: '/work/product/DESIGN.md'
        }),
        expect.objectContaining({
          href: 'file:///work/product/artifacts/tokens.json',
          kind: 'file',
          value: '/work/product/artifacts/tokens.json'
        })
      ])
    )
  })

  it('indexes plain workspace-relative paths from the final Artifacts handoff', () => {
    const artifacts = collectArtifactsForSession(makeSession({ cwd: '/work/product' }), [
      {
        content: 'Completed the prototype.\n\n## Artifacts\n- output/acme-overview.html',
        role: 'assistant',
        timestamp: 5500
      }
    ])

    expect(artifacts).toEqual([
      expect.objectContaining({
        href: 'file:///work/product/output/acme-overview.html',
        kind: 'file',
        value: '/work/product/output/acme-overview.html'
      })
    ])
  })

  it('normalizes parent-directory artifact paths without escaping the recorded workspace path incorrectly', () => {
    const artifacts = collectArtifactsForSession(makeSession({ cwd: '/work/product/src' }), [
      {
        content: JSON.stringify({ output_path: '../prototype/index.html' }),
        role: 'tool',
        timestamp: 6000
      }
    ])

    expect(artifacts[0]).toMatchObject({
      href: 'file:///work/product/prototype/index.html',
      value: '/work/product/prototype/index.html'
    })
  })

  it('deduplicates persisted write_file arguments, results, and the final Design handoff', () => {
    const messages = [
      {
        content: '',
        role: 'assistant',
        timestamp: 7000,
        tool_calls: [
          {
            function: {
              arguments: JSON.stringify({ content: '<html>prototype</html>', path: 'Design System Board.html' }),
              name: 'write_file'
            },
            id: 'call-1',
            type: 'function'
          }
        ]
      },
      {
        content: JSON.stringify({
          bytes_written: 100,
          files_modified: ['/work/product/Design System Board.html'],
          resolved_path: '/work/product/Design System Board.html'
        }),
        role: 'tool',
        timestamp: 8000
      },
      {
        content: 'Created `Design System Board.html`.',
        role: 'assistant',
        timestamp: 9000
      }
    ] as SessionMessage[]

    const artifacts = collectArtifactsForSession(makeSession({ cwd: '/work/product' }), messages)

    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]).toMatchObject({
      href: 'file:///work/product/Design System Board.html',
      kind: 'file',
      label: 'Design System Board.html',
      value: '/work/product/Design System Board.html'
    })
  })

  it('does not invent a base directory for a bare inline file without a session cwd', () => {
    const artifacts = collectArtifactsForSession(makeSession({ cwd: null }), [
      {
        content: 'Created `Design System Board.html`.',
        role: 'assistant',
        timestamp: 10_000
      }
    ])

    expect(artifacts).toEqual([])
  })

  it('ignores file-like strings under non-path tool-result keys', () => {
    const artifacts = collectArtifactsForSession(makeSession({ cwd: '/work/product' }), [
      {
        content: JSON.stringify({ message: 'finished', status: 'package.json' }),
        role: 'tool',
        timestamp: 11_000
      }
    ])

    expect(artifacts).toEqual([])
  })

  it('resolves Windows design paths and emits a canonical file URL', () => {
    const artifacts = collectArtifactsForSession(makeSession({ cwd: 'C:\\work\\product' }), [
      {
        content: 'Created `Design System Board.html`.',
        role: 'assistant',
        timestamp: 12_000
      }
    ])

    expect(artifacts[0]).toMatchObject({
      href: 'file:///C:/work/product/Design System Board.html',
      kind: 'file',
      value: 'C:/work/product/Design System Board.html'
    })
  })

  it('resolves remote image artifact thumbnails through the desktop fs bridge', async () => {
    const api = vi.fn(async ({ path }: { path: string }) => {
      if (path.startsWith('/api/fs/read-data-url?')) {
        return { dataUrl: 'data:image/jpeg;base64,cmVtb3Rl' }
      }

      throw new Error(`unexpected path ${path}`)
    })

    vi.stubGlobal('window', { fabricDesktop: { api } })
    $connection.set({ baseUrl: 'https://gw', mode: 'remote', token: 'secret' } as never)

    const path = '/Users/me/.fabric/skills/work-esab/references/images/manual-step03.jpeg'
    const downloadHref = `https://gw/api/files/download?path=${encodeURIComponent(path)}&token=secret`

    await expect(artifactImageSrc(path, downloadHref)).resolves.toBe('data:image/jpeg;base64,cmVtb3Rl')

    expect(api).toHaveBeenCalledWith({
      path: '/api/fs/read-data-url?path=%2FUsers%2Fme%2F.fabric%2Fskills%2Fwork-esab%2Freferences%2Fimages%2Fmanual-step03.jpeg'
    })
  })
})
