import {
  buildDesignPrompt,
  DESIGN_ARTIFACT_OPTIONS,
  DESIGN_SYSTEM_OPTIONS,
  type DesignArtifactKind,
  type DesignFidelity,
  type DesignSystemPreset
} from '@fabric/shared'
import { useStore } from '@nanostores/react'
import type * as React from 'react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { ErrorBanner } from '@/components/ui/error-state'
import { Loader } from '@/components/ui/loader'
import { RowButton } from '@/components/ui/row-button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n'
import { selectDesktopPaths } from '@/lib/desktop-fs'
import { isRemoteGateway } from '@/lib/media'
import { cn } from '@/lib/utils'
import {
  $designSystemInspection,
  $designSystemInspectionError,
  $designSystemInspectionStatus,
  $designSystems,
  $designSystemScope,
  $designSystemsStatus,
  clearDesignSystemInspection,
  type DesignSystemInspection,
  importDesignSystemZip,
  inspectDesignSystem,
  loadDesignSystems,
  type ManagedDesignSystem,
  removeDesignSystem,
  replaceDesignSystemZip
} from '@/store/design-systems'
import { notifyError } from '@/store/notifications'

import { PAGE_INSET_X } from '../layout-constants'

const PHASES = ['discover', 'direction', 'build', 'critique', 'deliver'] as const

export interface DesignStartRequest {
  prompt: string
}

export interface DesignViewProps extends React.ComponentProps<'section'> {
  currentCwd?: null | string
  onOpenArtifacts?: () => void
  onStartDesign: (request: DesignStartRequest) => void
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return '0 B'
  }

  if (value < 1024) {
    return `${value} B`
  }

  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(value < 10_240 ? 1 : 0)} KB`
  }

  return `${(value / (1024 * 1024)).toFixed(value < 10_485_760 ? 1 : 0)} MB`
}

function SourcePreflight({
  d,
  inspection,
  inspectionError,
  inspectionStatus,
  onRetry,
  retryLabel,
  system
}: {
  d: ReturnType<typeof useI18n>['t']['design']
  inspection: DesignSystemInspection | null
  inspectionError: null | string
  inspectionStatus: 'error' | 'idle' | 'loading' | 'ready'
  onRetry: () => void
  retryLabel: string
  system: ManagedDesignSystem
}) {
  const revisionShort = system.activeRevision.slice(0, 8)
  const filename = system.activeRevisionInfo.originalFilename

  return (
    <div className="mt-6 border-t border-(--ui-stroke-tertiary) pt-5" data-testid="source-preflight">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xs font-semibold text-(--ui-text-primary)">{d.preflightTitle}</h2>
          <p className="mt-1 text-xs leading-4 text-(--ui-text-secondary)">{d.preflightDescription}</p>
        </div>
      </div>

      <div className="mt-3 space-y-1 text-xs text-(--ui-text-secondary)">
        <p className="truncate text-(--ui-text-primary)">
          {filename} · {revisionShort}
        </p>
        {inspectionStatus === 'ready' && inspection ? (
          <p>
            {d.preflightSummary(inspection.fileCount, formatBytes(inspection.expandedBytes))}
            {inspection.omittedFileCount > 0
              ? ` · ${d.preflightOmitted(inspection.omittedFileCount)}`
              : null}
          </p>
        ) : null}
      </div>

      {inspectionStatus === 'loading' || inspectionStatus === 'idle' ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-(--ui-text-tertiary)">
          <Loader className="size-5" label={d.preflightLoading} type="lemniscate-bloom" />
          <span>{d.preflightLoading}</span>
        </div>
      ) : null}

      {inspectionStatus === 'error' ? (
        <div aria-live="assertive" className="mt-4 space-y-2" role="alert">
          <ErrorBanner>{inspectionError || d.preflightFailed}</ErrorBanner>
          <Button onClick={onRetry} size="sm" type="button" variant="outline">
            {retryLabel}
          </Button>
        </div>
      ) : null}

      {inspectionStatus === 'ready' && inspection ? (
        <div className="mt-4 space-y-4">
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.04em] text-(--ui-text-tertiary)">
              {d.preflightEntrypoints}
            </div>
            {inspection.entrypoints.designMd ||
            inspection.entrypoints.packageJson ||
            (inspection.entrypoints.html && inspection.entrypoints.html.length > 0) ||
            (inspection.entrypoints.tokenFiles && inspection.entrypoints.tokenFiles.length > 0) ? (
              <ul className="max-h-40 space-y-1 overflow-y-auto text-xs leading-4 text-(--ui-text-secondary)">
                {inspection.entrypoints.designMd ? (
                  <li>
                    <span className="text-(--ui-text-tertiary)">DESIGN.md · </span>
                    {inspection.entrypoints.designMd}
                  </li>
                ) : (
                  <li className="text-(--ui-text-tertiary)">{d.preflightNoDesignMd}</li>
                )}
                {inspection.entrypoints.packageJson ? (
                  <li>
                    <span className="text-(--ui-text-tertiary)">package.json · </span>
                    {inspection.entrypoints.packageJson}
                  </li>
                ) : null}
                {(inspection.entrypoints.html || []).map(path => (
                  <li key={`html-${path}`}>
                    <span className="text-(--ui-text-tertiary)">HTML · </span>
                    {path}
                  </li>
                ))}
                {(inspection.entrypoints.tokenFiles || []).map(path => (
                  <li key={`token-${path}`}>
                    <span className="text-(--ui-text-tertiary)">tokens · </span>
                    {path}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-(--ui-text-tertiary)">{d.preflightNoEntrypoints}</p>
            )}
            {inspection.omittedEntrypointCount > 0 ? (
              <p className="mt-2 text-[11px] text-(--ui-text-tertiary)">
                {d.preflightOmitted(inspection.omittedEntrypointCount)}
              </p>
            ) : null}
          </div>

          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.04em] text-(--ui-text-tertiary)">
              {d.preflightInventory}
            </div>
            <ul className="max-h-40 space-y-1 overflow-y-auto text-xs leading-4 text-(--ui-text-secondary)">
              {inspection.files.map(file => (
                <li className="flex min-w-0 items-baseline justify-between gap-3" key={file.path}>
                  <span className="min-w-0 truncate">{file.path}</span>
                  <span className="shrink-0 font-mono text-[11px] text-(--ui-text-tertiary)">
                    {formatBytes(file.size)}
                  </span>
                </li>
              ))}
            </ul>
            {inspection.omittedFileCount > 0 ? (
              <p className="mt-2 text-[11px] text-(--ui-text-tertiary)">
                {d.preflightOmitted(inspection.omittedFileCount)}
              </p>
            ) : null}
          </div>

          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.04em] text-(--ui-text-tertiary)">
              {d.preflightDesignMd}
            </div>
            {inspection.designMdPreview ? (
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary) px-3 py-2 font-mono text-[11px] leading-4 text-(--ui-text-secondary)">
                {inspection.designMdPreview.text}
                {inspection.designMdPreview.truncated ? `\n\n${d.preflightTruncated}` : ''}
              </pre>
            ) : (
              <p className="text-xs text-(--ui-text-tertiary)">{d.preflightNoDesignMd}</p>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function DesignView({
  className,
  currentCwd,
  onOpenArtifacts,
  onStartDesign,
  ...props
}: DesignViewProps) {
  const { t } = useI18n()
  const d = t.design
  const [brief, setBrief] = useState('')
  const [artifact, setArtifact] = useState<DesignArtifactKind>('prototype')
  const [fidelity, setFidelity] = useState<DesignFidelity>('high')
  const [system, setSystem] = useState<DesignSystemPreset>('project')
  const [selectedManagedSystemId, setSelectedManagedSystemId] = useState<null | string>(null)
  const [importing, setImporting] = useState(false)
  const managedSystems = useStore($designSystems)
  const designSystemScope = useStore($designSystemScope)
  const libraryStatus = useStore($designSystemsStatus)
  const inspection = useStore($designSystemInspection)
  const inspectionStatus = useStore($designSystemInspectionStatus)
  const inspectionError = useStore($designSystemInspectionError)
  const selectedManagedSystem = managedSystems.find(item => item.id === selectedManagedSystemId)

  const matchingInspection =
    selectedManagedSystem &&
    inspection &&
    inspection.designSystemId === selectedManagedSystem.id &&
    inspection.revisionSha256 === selectedManagedSystem.activeRevision
      ? inspection
      : null

  const selectedSourceReady =
    !selectedManagedSystem || (inspectionStatus === 'ready' && matchingInspection !== null)

  useEffect(() => {
    void loadDesignSystems().catch(error => notifyError(error, d.importFailed))
  }, [d.importFailed, designSystemScope])

  useEffect(() => {
    if (!selectedManagedSystem) {
      clearDesignSystemInspection()

      return
    }

    void inspectDesignSystem(selectedManagedSystem).catch(() => {
      // Store already records the error state for the preflight panel.
    })
  }, [selectedManagedSystem, designSystemScope])

  const chooseArchive = async (title: string) => {
    const paths = await selectDesktopPaths({
      defaultPath: currentCwd || undefined,
      filters: [{ extensions: ['zip'], name: 'ZIP archives' }],
      multiple: false,
      title
    })

    return paths[0] || null
  }

  const importArchive = async () => {
    try {
      const path = await chooseArchive(d.addArchive)

      if (!path) {
        return
      }

      setImporting(true)
      const result = await importDesignSystemZip(path)
      clearDesignSystemInspection()
      setSelectedManagedSystemId(result.system.id)
    } catch (error) {
      notifyError(error, d.importFailed)
    } finally {
      setImporting(false)
    }
  }

  const replaceArchive = async (saved: ManagedDesignSystem) => {
    try {
      const path = await chooseArchive(d.replaceArchive)

      if (!path) {
        return
      }

      setImporting(true)
      const result = await replaceDesignSystemZip(saved, path)
      clearDesignSystemInspection()
      setSelectedManagedSystemId(result.system.id)
    } catch (error) {
      notifyError(error, d.importFailed)
    } finally {
      setImporting(false)
    }
  }

  const revealArchive = async (saved: ManagedDesignSystem) => {
    try {
      const revealed = await window.hermesDesktop?.revealPath?.(saved.contentPath)

      if (!revealed) {
        throw new Error(d.revealFailed)
      }
    } catch (error) {
      notifyError(error, d.revealFailed)
    }
  }

  const forgetSystem = async (saved: ManagedDesignSystem) => {
    try {
      await removeDesignSystem(saved)

      if (selectedManagedSystemId === saved.id) {
        setSelectedManagedSystemId(null)
      }
    } catch (error) {
      notifyError(error, d.importFailed)
    }
  }

  const startDesign = () => {
    const normalizedBrief = brief.trim()

    if (!normalizedBrief || !selectedSourceReady) {
      return
    }

    const prompt = buildDesignPrompt({
      artifact,
      brief: normalizedBrief,
      fidelity,
      system,
      systemSource: selectedManagedSystem
        ? {
            contentPath: selectedManagedSystem.contentPath,
            id: selectedManagedSystem.id,
            inspection: matchingInspection
              ? {
                  entrypoints: matchingInspection.entrypoints,
                  expandedBytes: matchingInspection.expandedBytes,
                  fileCount: matchingInspection.fileCount,
                  files: matchingInspection.files,
                  omittedEntrypointCount: matchingInspection.omittedEntrypointCount,
                  omittedFileCount: matchingInspection.omittedFileCount
                }
              : undefined,
            kind: 'managed',
            name: selectedManagedSystem.name,
            revisionSha256: selectedManagedSystem.activeRevision
          }
        : undefined
    })

    onStartDesign({ prompt })
  }

  return (
    <section
      {...props}
      className={cn(
        'flex h-full min-w-0 flex-col overflow-y-auto bg-(--ui-chat-surface-background) pt-(--titlebar-height)',
        className
      )}
    >
      <div className={cn('mx-auto flex w-full max-w-5xl flex-1 flex-col pb-8 pt-8', PAGE_INSET_X)}>
        <header className="flex items-start justify-between gap-4 border-b border-(--ui-stroke-tertiary) pb-6">
          <div className="max-w-2xl">
            <div className="mb-3 flex size-8 items-center justify-center rounded-[4px] bg-(--ui-bg-tertiary) text-(--ui-text-secondary)">
              <Codicon name="symbol-color" size="1.1rem" />
            </div>
            <h1 className="text-lg font-semibold tracking-[-0.015em] text-(--ui-text-primary)">{d.title}</h1>
            <p className="mt-1.5 max-w-xl text-xs leading-5 text-(--ui-text-secondary)">{d.subtitle}</p>
          </div>
          {onOpenArtifacts ? (
            <Button className="shrink-0" onClick={onOpenArtifacts} variant="outline">
              <Codicon name="files" size="1rem" />
              {d.viewArtifacts}
            </Button>
          ) : null}
        </header>

        <div className="grid flex-1 gap-8 pt-7 lg:grid-cols-[minmax(0,1fr)_18rem] lg:gap-10">
          <form
            className="min-w-0 space-y-6"
            onSubmit={event => {
              event.preventDefault()
              startDesign()
            }}
          >
            <div>
              <label className="mb-2 block text-xs font-medium text-(--ui-text-primary)" htmlFor="design-brief">
                {d.briefLabel}
              </label>
              <Textarea
                autoFocus
                className="min-h-36 resize-y py-2.5 text-sm leading-5"
                id="design-brief"
                maxLength={4000}
                onChange={event => setBrief(event.target.value)}
                placeholder={d.briefPlaceholder}
                value={brief}
              />
            </div>

            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label
                  className="mb-2 block text-xs font-medium text-(--ui-text-primary)"
                  htmlFor="design-deliverable"
                >
                  {d.deliverableLabel}
                </label>
                <Select onValueChange={value => setArtifact(value as DesignArtifactKind)} value={artifact}>
                  <SelectTrigger className="w-full" id="design-deliverable">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DESIGN_ARTIFACT_OPTIONS.map(option => (
                      <SelectItem key={option.id} value={option.id}>
                        {d.artifact[option.id]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className="mb-2 block text-xs font-medium text-(--ui-text-primary)" htmlFor="design-system">
                  {d.systemLabel}
                </label>
                <Select
                  onValueChange={value => {
                    setSystem(value as DesignSystemPreset)
                    setSelectedManagedSystemId(null)
                  }}
                  value={system}
                >
                  <SelectTrigger className="w-full" id="design-system">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DESIGN_SYSTEM_OPTIONS.map(option => (
                      <SelectItem key={option.id} value={option.id}>
                        {d.system[option.id]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  className="mt-2"
                  disabled={importing}
                  onClick={() => void importArchive()}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  <Codicon name="archive" size="1rem" />
                  {d.addArchive}
                </Button>
                {selectedManagedSystem ? (
                  <p className="mt-2 flex items-center gap-1.5 truncate text-[11px] text-(--ui-text-secondary)">
                    <Codicon name="check" size="0.85rem" />
                    {d.savedSystemPrefix} · {selectedManagedSystem.name}
                  </p>
                ) : null}
              </div>
            </div>

            <div>
              <div className="mb-2 text-xs font-medium text-(--ui-text-primary)">{d.fidelityLabel}</div>
              <SegmentedControl
                onChange={setFidelity}
                options={[
                  { id: 'wireframe', label: d.fidelity.wireframe },
                  { id: 'high', label: d.fidelity.high }
                ]}
                value={fidelity}
              />
            </div>

            {selectedManagedSystem ? (
              <SourcePreflight
                d={d}
                inspection={matchingInspection}
                inspectionError={inspectionError}
                inspectionStatus={
                  matchingInspection
                    ? inspectionStatus
                    : inspectionStatus === 'error'
                      ? 'error'
                      : 'loading'
                }
                onRetry={() => {
                  void inspectDesignSystem(selectedManagedSystem).catch(() => {
                    // Store already records the error state for the preflight panel.
                  })
                }}
                retryLabel={t.common.retry}
                system={selectedManagedSystem}
              />
            ) : null}

            <div className="flex flex-wrap items-center gap-3 border-t border-(--ui-stroke-tertiary) pt-5">
              <Button disabled={!brief.trim() || !selectedSourceReady} size="lg" type="submit">
                <Codicon name="wand" />
                {d.start}
              </Button>
              <span className="max-w-sm text-xs leading-4 text-(--ui-text-tertiary)">{d.reviewHint}</span>
            </div>
          </form>

          <aside className="border-t border-(--ui-stroke-tertiary) pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-xs font-semibold text-(--ui-text-primary)">{d.libraryTitle}</h2>
                <p className="mt-2 text-xs leading-4 text-(--ui-text-secondary)">{d.libraryDescription}</p>
              </div>
              <Button
                aria-label={d.addArchive}
                disabled={importing}
                onClick={() => void importArchive()}
                size="icon-xs"
                title={d.addArchive}
                type="button"
                variant="ghost"
              >
                <Codicon name="add" size="1rem" />
              </Button>
            </div>

            <div
              aria-busy={libraryStatus === 'loading'}
              className="mt-4 border-y border-(--ui-stroke-tertiary)"
              role="radiogroup"
            >
              {managedSystems.length === 0 ? (
                <p className="py-3 text-xs leading-4 text-(--ui-text-tertiary)">{d.libraryEmpty}</p>
              ) : (
                managedSystems.map(saved => {
                  const selected = selectedManagedSystem?.id === saved.id

                  return (
                    <div
                      className={cn(
                        'flex min-w-0 items-center gap-1 border-b border-(--ui-stroke-tertiary) py-1 last:border-b-0',
                        selected && 'bg-(--ui-bg-tertiary)'
                      )}
                      key={saved.id}
                    >
                      <RowButton
                        aria-checked={selected}
                        className="min-w-0 flex-1 px-2 py-1.5 text-left outline-none focus-visible:ring-1 focus-visible:ring-(--ui-focus-ring)"
                        onClick={() => {
                          clearDesignSystemInspection()
                          setSelectedManagedSystemId(current => (current === saved.id ? null : saved.id))
                        }}
                        role="radio"
                      >
                        <span className="block truncate text-xs font-medium text-(--ui-text-primary)">{saved.name}</span>
                        <span
                          className="mt-0.5 block truncate text-[11px] text-(--ui-text-tertiary)"
                          title={saved.activeRevisionInfo.originalFilename}
                        >
                          {saved.activeRevisionInfo.originalFilename} · {saved.activeRevision.slice(0, 8)}
                        </span>
                      </RowButton>
                      <div className="flex shrink-0 items-center pr-1">
                        <Button
                          aria-label={`${d.replaceArchive}: ${saved.name}`}
                          disabled={importing}
                          onClick={() => void replaceArchive(saved)}
                          size="icon-xs"
                          title={d.replaceArchive}
                          type="button"
                          variant="ghost"
                        >
                          <Codicon name="replace-all" size="0.9rem" />
                        </Button>
                        {!isRemoteGateway() ? (
                          <Button
                            aria-label={`${d.revealSource}: ${saved.name}`}
                            onClick={() => void revealArchive(saved)}
                            size="icon-xs"
                            title={d.revealSource}
                            type="button"
                            variant="ghost"
                          >
                            <Codicon name="folder-opened" size="0.9rem" />
                          </Button>
                        ) : null}
                        <Button
                          aria-label={`${d.removeSystem}: ${saved.name}`}
                          onClick={() => void forgetSystem(saved)}
                          size="icon-xs"
                          title={d.removeSystem}
                          type="button"
                          variant="ghost"
                        >
                          <Codicon name="trash" size="0.9rem" />
                        </Button>
                      </div>
                    </div>
                  )
                })
              )}
            </div>

            <div className="mt-8 border-t border-(--ui-stroke-tertiary) pt-6">
              <h2 className="text-xs font-semibold text-(--ui-text-primary)">{d.contractTitle}</h2>
              <p className="mt-2 text-xs leading-4 text-(--ui-text-secondary)">{d.contractDescription}</p>
              <ol className="mt-6 space-y-4">
                {PHASES.map((phase, index) => (
                  <li className="grid grid-cols-[1.5rem_minmax(0,1fr)] items-start gap-2" key={phase}>
                    <span className="font-mono text-xs leading-4 text-(--ui-text-tertiary)">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span className="text-xs leading-4 text-(--ui-text-secondary)">{d.phases[phase]}</span>
                  </li>
                ))}
              </ol>
            </div>
          </aside>
        </div>
      </div>
    </section>
  )
}
