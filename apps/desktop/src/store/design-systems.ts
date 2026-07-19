import { atom } from 'nanostores'

import type { FabricConnection } from '@/global'
import { $activeGatewayProfile, normalizeProfileKey } from '@/store/profile'
import { $connection } from '@/store/session'

export interface DesignSystemRevisionInfo {
  archiveBytes: number
  entryCount: number
  entrypoints: {
    designMd?: string
    html?: string[]
    packageJson?: string
    tokenFiles?: string[]
  }
  expandedBytes: number
  importedAt: string
  originalFilename: string
  sha256: string
}

export interface ManagedDesignSystem {
  activeRevision: string
  activeRevisionInfo: DesignSystemRevisionInfo
  contentPath: string
  createdAt: string
  description: string
  generation: number
  id: string
  name: string
  revisionManifestPath: string
  schemaVersion: 1
  sourceKind: 'claude-design-zip'
  updatedAt: string
}

export interface DesignSystemInspectionFile {
  path: string
  size: number
}

export interface DesignSystemInspectionEntrypoints {
  designMd?: string
  html?: string[]
  packageJson?: string
  tokenFiles?: string[]
}

export interface DesignSystemDesignMdPreview {
  path: string
  text: string
  truncated: boolean
}

export interface DesignSystemInspection {
  designMdPreview: DesignSystemDesignMdPreview | null
  designSystemId: string
  entrypoints: DesignSystemInspectionEntrypoints
  expandedBytes: number
  fileCount: number
  files: DesignSystemInspectionFile[]
  omittedEntrypointCount: number
  omittedFileCount: number
  revisionSha256: string
}

export type DesignSystemsStatus = 'error' | 'idle' | 'loading' | 'ready'
export type DesignSystemInspectionStatus = 'error' | 'idle' | 'loading' | 'ready'

interface DesignSystemImportResult {
  deduplicated: boolean
  system: ManagedDesignSystem
  warnings: string[]
}

interface DesignSystemListResponse {
  systems: ManagedDesignSystem[]
}

interface DesignSystemInspectionResponse {
  inspection: DesignSystemInspection
}

export const $designSystems = atom<ManagedDesignSystem[]>([])
export const $designSystemsStatus = atom<DesignSystemsStatus>('idle')
export const $designSystemsError = atom<null | string>(null)
export const $designSystemInspection = atom<DesignSystemInspection | null>(null)
export const $designSystemInspectionStatus = atom<DesignSystemInspectionStatus>('idle')
export const $designSystemInspectionError = atom<null | string>(null)

function connectionKey(connection: FabricConnection | null): string {
  if (!connection || connection.mode !== 'remote') {
    return 'local'
  }

  return `remote:${connection.baseUrl}`
}

export function designSystemScopeKey(
  profile = normalizeProfileKey($activeGatewayProfile.get()),
  connection = $connection.get()
): string {
  return `${connectionKey(connection)}:${normalizeProfileKey(profile)}`
}

let observedScope = designSystemScopeKey()
let inspectionRequestVersion = 0
export const $designSystemScope = atom(observedScope)

function resetForScopeChange(): void {
  const nextScope = designSystemScopeKey()

  if (nextScope === observedScope) {
    return
  }

  observedScope = nextScope
  $designSystemScope.set(nextScope)
  $designSystems.set([])
  $designSystemsError.set(null)
  $designSystemsStatus.set('idle')
  inspectionRequestVersion += 1
  $designSystemInspection.set(null)
  $designSystemInspectionError.set(null)
  $designSystemInspectionStatus.set('idle')
}

$activeGatewayProfile.subscribe(resetForScopeChange)
$connection.subscribe(resetForScopeChange)

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function archiveDisplayName(sourcePath: string): string {
  const filename = sourcePath.replace(/\\/g, '/').split('/').pop() || ''

  return filename.replace(/\.zip$/i, '').replace(/[-_]+/g, ' ').trim() || 'Imported design system'
}

function captureTarget() {
  return {
    profile: normalizeProfileKey($activeGatewayProfile.get()),
    scope: designSystemScopeKey()
  }
}

function updateSystem(system: ManagedDesignSystem): void {
  const next = $designSystems.get().filter(item => item.id !== system.id)
  next.unshift(system)
  next.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  $designSystems.set(next)
}

export async function loadDesignSystems(): Promise<ManagedDesignSystem[]> {
  const target = captureTarget()
  $designSystemsError.set(null)
  $designSystemsStatus.set('loading')

  try {
    const response = await window.fabricDesktop.api<DesignSystemListResponse>({
      path: '/api/design-systems',
      profile: target.profile
    })

    const systems = Array.isArray(response.systems) ? response.systems : []

    if (designSystemScopeKey() === target.scope) {
      $designSystems.set(systems)
      $designSystemsStatus.set('ready')
    }

    return systems
  } catch (error) {
    if (designSystemScopeKey() === target.scope) {
      $designSystemsError.set(messageFromError(error))
      $designSystemsStatus.set('error')
    }

    throw error
  }
}

export async function importDesignSystemZip(sourcePath: string, name?: string): Promise<DesignSystemImportResult> {
  const target = captureTarget()
  const importer = window.fabricDesktop.importDesignSystemZip

  if (!importer) {
    throw new Error('This Fabric backend does not support managed design systems yet. Update Fabric and try again.')
  }

  const result = await window.fabricDesktop.importDesignSystemZip<DesignSystemImportResult>({
    generation: 0,
    name: name?.trim() || archiveDisplayName(sourcePath),
    profile: target.profile,
    sourcePath
  })

  if (designSystemScopeKey() === target.scope) {
    updateSystem(result.system)
    $designSystemsError.set(null)
    $designSystemsStatus.set('ready')
  }

  return result
}

export async function replaceDesignSystemZip(
  system: ManagedDesignSystem,
  sourcePath: string
): Promise<DesignSystemImportResult> {
  const target = captureTarget()
  const importer = window.fabricDesktop.importDesignSystemZip

  if (!importer) {
    throw new Error('This Fabric backend does not support managed design systems yet. Update Fabric and try again.')
  }

  const result = await window.fabricDesktop.importDesignSystemZip<DesignSystemImportResult>({
    generation: system.generation,
    name: system.name,
    profile: target.profile,
    replaceId: system.id,
    sourcePath
  })

  if (designSystemScopeKey() === target.scope) {
    updateSystem(result.system)
  }

  return result
}

export async function removeDesignSystem(system: ManagedDesignSystem): Promise<void> {
  const target = captureTarget()

  await window.fabricDesktop.api<{ ok: boolean }>({
    body: { expectedGeneration: system.generation },
    method: 'DELETE',
    path: `/api/design-systems/${encodeURIComponent(system.id)}`,
    profile: target.profile
  })

  if (designSystemScopeKey() === target.scope) {
    $designSystems.set($designSystems.get().filter(item => item.id !== system.id))

    if ($designSystemInspection.get()?.designSystemId === system.id) {
      clearDesignSystemInspection()
    }
  }
}

export function clearDesignSystemInspection(): void {
  inspectionRequestVersion += 1
  $designSystemInspection.set(null)
  $designSystemInspectionError.set(null)
  $designSystemInspectionStatus.set('idle')
}

export async function inspectDesignSystem(system: ManagedDesignSystem): Promise<DesignSystemInspection | null> {
  const target = captureTarget()
  const requestVersion = ++inspectionRequestVersion
  $designSystemInspectionError.set(null)
  $designSystemInspectionStatus.set('loading')

  try {
    const response = await window.fabricDesktop.api<DesignSystemInspectionResponse>({
      path: `/api/design-systems/${encodeURIComponent(system.id)}/inspection`,
      profile: target.profile
    })

    const inspection = response.inspection

    if (
      !inspection ||
      inspection.designSystemId !== system.id ||
      inspection.revisionSha256 !== system.activeRevision
    ) {
      throw new Error('Design-system inspection did not match the selected revision. Refresh and try again.')
    }

    if (designSystemScopeKey() !== target.scope || requestVersion !== inspectionRequestVersion) {
      return inspection
    }

    $designSystemInspection.set(inspection)
    $designSystemInspectionStatus.set('ready')

    return inspection
  } catch (error) {
    if (designSystemScopeKey() === target.scope && requestVersion === inspectionRequestVersion) {
      $designSystemInspection.set(null)
      $designSystemInspectionError.set(messageFromError(error))
      $designSystemInspectionStatus.set('error')
    }

    throw error
  }
}
