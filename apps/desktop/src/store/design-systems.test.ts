import { beforeEach, describe, expect, it, vi } from 'vitest'

import { $activeGatewayProfile } from '@/store/profile'
import { $connection } from '@/store/session'

import {
  $designSystems,
  designSystemScopeKey,
  importDesignSystemZip,
  loadDesignSystems,
  type ManagedDesignSystem,
  removeDesignSystem
} from './design-systems'

const system: ManagedDesignSystem = {
  activeRevision: 'abc123',
  activeRevisionInfo: {
    archiveBytes: 100,
    entryCount: 2,
    entrypoints: { designMd: 'DESIGN.md' },
    expandedBytes: 200,
    importedAt: '2026-07-16T00:00:00Z',
    originalFilename: 'Acme.zip',
    sha256: 'abc123'
  },
  contentPath: '/managed/acme/content',
  createdAt: '2026-07-16T00:00:00Z',
  description: '',
  generation: 1,
  id: 'system-1',
  name: 'Acme',
  revisionManifestPath: '/managed/acme/revision.json',
  schemaVersion: 1,
  sourceKind: 'claude-design-zip',
  updatedAt: '2026-07-16T00:00:00Z'
}

function installBridge(api = vi.fn()) {
  const importZip = vi.fn()

  Object.defineProperty(window, 'fabricDesktop', {
    configurable: true,
    value: { api, importDesignSystemZip: importZip }
  })

  return { api, importZip }
}

describe('design system store', () => {
  beforeEach(() => {
    $activeGatewayProfile.set('default')
    $connection.set(null)
    $designSystems.set([])
  })

  it('keys libraries by connection and profile', () => {
    expect(designSystemScopeKey('default', null)).toBe('local:default')
    expect(
      designSystemScopeKey('design', {
        baseUrl: 'https://fabric.example',
        mode: 'remote'
      } as never)
    ).toBe('remote:https://fabric.example:design')
  })

  it('loads the active profile library from the Fabric backend', async () => {
    const { api } = installBridge(vi.fn().mockResolvedValue({ systems: [system] }))

    await expect(loadDesignSystems()).resolves.toEqual([system])
    expect($designSystems.get()).toEqual([system])
    expect(api).toHaveBeenCalledWith({ path: '/api/design-systems', profile: 'default' })
  })

  it('imports through the narrow desktop bridge and keeps only managed metadata', async () => {
    const { importZip } = installBridge()
    importZip.mockResolvedValue({ deduplicated: false, system, warnings: [] })

    await expect(importDesignSystemZip('/Users/alice/Acme.zip')).resolves.toMatchObject({ system })
    expect(importZip).toHaveBeenCalledWith({
      generation: 0,
      name: 'Acme',
      profile: 'default',
      sourcePath: '/Users/alice/Acme.zip'
    })
    expect($designSystems.get()).toEqual([system])
  })

  it('removes managed metadata through the profile-scoped API', async () => {
    const { api } = installBridge(vi.fn().mockResolvedValue({ ok: true }))
    $designSystems.set([system])

    await removeDesignSystem(system)

    expect(api).toHaveBeenCalledWith({
      body: { expectedGeneration: 1 },
      method: 'DELETE',
      path: '/api/design-systems/system-1',
      profile: 'default'
    })
    expect($designSystems.get()).toEqual([])
  })
})
