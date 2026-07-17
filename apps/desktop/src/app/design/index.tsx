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
import { RowButton } from '@/components/ui/row-button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n'
import { selectDesktopPaths } from '@/lib/desktop-fs'
import { isRemoteGateway } from '@/lib/media'
import { cn } from '@/lib/utils'
import {
  $designSystems,
  $designSystemScope,
  $designSystemsStatus,
  importDesignSystemZip,
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
  const selectedManagedSystem = managedSystems.find(item => item.id === selectedManagedSystemId)

  useEffect(() => {
    void loadDesignSystems().catch(error => notifyError(error, d.importFailed))
  }, [d.importFailed, designSystemScope])

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
      setSelectedManagedSystemId(result.system.id)
    } catch (error) {
      notifyError(error, d.importFailed)
    } finally {
      setImporting(false)
    }
  }

  const revealArchive = async (saved: ManagedDesignSystem) => {
    try {
      const revealed = await window.fabricDesktop?.revealPath?.(saved.contentPath)

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

    if (!normalizedBrief) {
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

            <div className="flex flex-wrap items-center gap-3 border-t border-(--ui-stroke-tertiary) pt-5">
              <Button disabled={!brief.trim()} size="lg" type="submit">
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
                        onClick={() =>
                          setSelectedManagedSystemId(current => (current === saved.id ? null : saved.id))
                        }
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
