// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $designSystems, type ManagedDesignSystem } from '@/store/design-systems'

const selectDesktopPaths = vi.hoisted(() => vi.fn())

vi.mock('@/lib/desktop-fs', () => ({ selectDesktopPaths }))

import { DesignView } from './index'

const managedSystem: ManagedDesignSystem = {
  activeRevision: 'abc123456789',
  activeRevisionInfo: {
    archiveBytes: 100,
    entryCount: 2,
    entrypoints: { designMd: 'DESIGN.md' },
    expandedBytes: 200,
    importedAt: '2026-07-16T00:00:00Z',
    originalFilename: 'claude-product-system.zip',
    sha256: 'abc123456789'
  },
  contentPath: '/managed/systems/system-1/revisions/abc123456789/content',
  createdAt: '2026-07-16T00:00:00Z',
  description: '',
  generation: 1,
  id: 'system-1',
  name: 'claude product system',
  revisionManifestPath: '/managed/systems/system-1/revisions/abc123456789/revision.json',
  schemaVersion: 1,
  sourceKind: 'claude-design-zip',
  updatedAt: '2026-07-16T00:00:00Z'
}

function installBridge() {
  const api = vi.fn().mockResolvedValue({ systems: [] })
  const importZip = vi.fn().mockResolvedValue({ deduplicated: false, system: managedSystem, warnings: [] })

  Object.defineProperty(window, 'hermesDesktop', {
    configurable: true,
    value: { api, importDesignSystemZip: importZip, revealPath: vi.fn() }
  })

  return { api, importZip }
}

beforeEach(() => {
  $designSystems.set([])
  installBridge()
})

afterEach(() => {
  cleanup()
  selectDesktopPaths.mockReset()
})

describe('DesignView', () => {
  it('keeps the action disabled until the brief has content', () => {
    render(<DesignView onStartDesign={vi.fn()} />)

    const start = screen.getByRole('button', { name: 'Start in chat' })
    expect(start).toHaveProperty('disabled', true)

    fireEvent.change(screen.getByLabelText('Brief'), {
      target: { value: 'Design a repository onboarding flow' }
    })

    expect(start).toHaveProperty('disabled', false)
  })

  it('hands a reviewable design prompt to the existing chat flow', () => {
    const onStartDesign = vi.fn()
    render(<DesignView onStartDesign={onStartDesign} />)

    fireEvent.change(screen.getByLabelText('Brief'), {
      target: { value: 'Design a repository onboarding flow' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Start in chat' }))

    expect(onStartDesign).toHaveBeenCalledTimes(1)
    expect(onStartDesign.mock.calls[0][0].prompt).toContain('/design Design a repository onboarding flow')
    expect(onStartDesign.mock.calls[0][0].prompt).toContain('Artifact handoff:')
  })

  it('imports a Claude Design ZIP into the managed library and uses its validated revision', async () => {
    selectDesktopPaths.mockResolvedValue(['/Users/alice/Downloads/claude-product-system.zip'])
    const { importZip } = installBridge()
    const onStartDesign = vi.fn()
    render(<DesignView currentCwd="/Users/alice/project" onStartDesign={onStartDesign} />)

    fireEvent.click(screen.getAllByRole('button', { name: 'Add Claude Design ZIP' })[0]!)

    expect(await screen.findByText('claude product system')).toBeTruthy()
    expect(screen.getByText('claude-product-system.zip · abc12345')).toBeTruthy()
    await waitFor(() => {
      expect(screen.getByRole('radio', { name: /claude product system/i }).getAttribute('aria-checked')).toBe('true')
    })
    expect(importZip).toHaveBeenCalledWith({
      generation: 0,
      name: 'claude product system',
      profile: 'default',
      sourcePath: '/Users/alice/Downloads/claude-product-system.zip'
    })

    fireEvent.change(screen.getByLabelText('Brief'), {
      target: { value: 'Apply the imported system to settings' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Start in chat' }))

    expect(onStartDesign).toHaveBeenCalledWith({
      prompt: expect.stringContaining('Fabric-managed design system')
    })
    expect(onStartDesign.mock.calls[0][0].prompt).toContain('revision abc123456789')
    expect(onStartDesign.mock.calls[0][0].prompt).toContain(managedSystem.contentPath)
  })
})
