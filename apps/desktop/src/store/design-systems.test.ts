import { beforeEach, describe, expect, it, vi } from 'vitest'

import { $activeGatewayProfile } from '@/store/profile'
import { $connection } from '@/store/session'

import {
  $designSystemInspection,
  $designSystemInspectionStatus,
  $designSystems,
  clearDesignSystemInspection,
  type DesignSystemInspection,
  designSystemScopeKey,
  importDesignSystemZip,
  inspectDesignSystem,
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

const inspection: DesignSystemInspection = {
  designMdPreview: {
    path: 'DESIGN.md',
    text: '# Acme',
    truncated: false
  },
  designSystemId: 'system-1',
  entrypoints: {
    designMd: 'DESIGN.md',
    packageJson: 'package.json'
  },
  expandedBytes: 200,
  fileCount: 2,
  files: [
    { path: 'DESIGN.md', size: 6 },
    { path: 'package.json', size: 2 }
  ],
  omittedEntrypointCount: 0,
  omittedFileCount: 0,
  revisionSha256: 'abc123'
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
    clearDesignSystemInspection()
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

  it('requests inspection with the captured profile and encoded system id', async () => {
    const { api } = installBridge(vi.fn().mockResolvedValue({ inspection }))
    $activeGatewayProfile.set('design')

    await expect(inspectDesignSystem(system)).resolves.toEqual(inspection)
    expect(api).toHaveBeenCalledWith({
      path: '/api/design-systems/system-1/inspection',
      profile: 'design'
    })
    expect($designSystemInspection.get()).toEqual(inspection)
    expect($designSystemInspectionStatus.get()).toBe('ready')
  })

  it('rejects an inspection that does not match the selected managed revision', async () => {
    installBridge(
      vi.fn().mockResolvedValue({
        inspection: { ...inspection, revisionSha256: 'unexpected-revision' }
      })
    )

    await expect(inspectDesignSystem(system)).rejects.toThrow('did not match the selected revision')
    expect($designSystemInspection.get()).toBeNull()
    expect($designSystemInspectionStatus.get()).toBe('error')
  })

  it('ignores stale inspection responses after the connection or profile changes', async () => {
    let resolveRequest: ((value: { inspection: DesignSystemInspection }) => void) | undefined

    const pending = new Promise<{ inspection: DesignSystemInspection }>(resolve => {
      resolveRequest = resolve
    })

    const { api } = installBridge(vi.fn().mockReturnValue(pending))

    const request = inspectDesignSystem(system)
    expect($designSystemInspectionStatus.get()).toBe('loading')

    $activeGatewayProfile.set('other')
    resolveRequest?.({ inspection })
    await expect(request).resolves.toEqual(inspection)

    expect(api).toHaveBeenCalledTimes(1)
    expect($designSystemInspection.get()).toBeNull()
    expect($designSystemInspectionStatus.get()).toBe('idle')
  })

  it('keeps only the newest inspection when managed-system requests resolve out of order', async () => {
    const secondSystem: ManagedDesignSystem = {
      ...system,
      activeRevision: 'def456',
      activeRevisionInfo: {
        ...system.activeRevisionInfo,
        sha256: 'def456'
      },
      id: 'system-2',
      name: 'Beta'
    }

    const secondInspection: DesignSystemInspection = {
      ...inspection,
      designSystemId: secondSystem.id,
      revisionSha256: secondSystem.activeRevision
    }

    let resolveFirst: ((value: { inspection: DesignSystemInspection }) => void) | undefined
    let resolveSecond: ((value: { inspection: DesignSystemInspection }) => void) | undefined

    const firstPending = new Promise<{ inspection: DesignSystemInspection }>(resolve => {
      resolveFirst = resolve
    })

    const secondPending = new Promise<{ inspection: DesignSystemInspection }>(resolve => {
      resolveSecond = resolve
    })

    const { api } = installBridge(
      vi.fn().mockReturnValueOnce(firstPending).mockReturnValueOnce(secondPending)
    )

    const firstRequest = inspectDesignSystem(system)
    const secondRequest = inspectDesignSystem(secondSystem)

    resolveSecond?.({ inspection: secondInspection })
    await expect(secondRequest).resolves.toEqual(secondInspection)
    expect($designSystemInspection.get()).toEqual(secondInspection)

    resolveFirst?.({ inspection })
    await expect(firstRequest).resolves.toEqual(inspection)
    expect(api).toHaveBeenCalledTimes(2)
    expect($designSystemInspection.get()).toEqual(secondInspection)
    expect($designSystemInspectionStatus.get()).toBe('ready')
  })
})
