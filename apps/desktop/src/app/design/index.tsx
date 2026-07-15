import {
  buildDesignPrompt,
  DESIGN_ARTIFACT_OPTIONS,
  DESIGN_SYSTEM_OPTIONS,
  type DesignArtifactKind,
  type DesignFidelity,
  type DesignSystemPreset
} from '@fabric/shared'
import type * as React from 'react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

import { PAGE_INSET_X } from '../layout-constants'

const PHASES = ['discover', 'direction', 'build', 'critique', 'deliver'] as const

export interface DesignViewProps extends React.ComponentProps<'section'> {
  onStartDesign: (prompt: string) => void
}

export function DesignView({ className, onStartDesign, ...props }: DesignViewProps) {
  const { t } = useI18n()
  const d = t.design
  const [brief, setBrief] = useState('')
  const [artifact, setArtifact] = useState<DesignArtifactKind>('prototype')
  const [fidelity, setFidelity] = useState<DesignFidelity>('high')
  const [system, setSystem] = useState<DesignSystemPreset>('project')

  const startDesign = () => {
    if (!brief.trim()) {
      return
    }

    onStartDesign(buildDesignPrompt({ artifact, brief, fidelity, system }))
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
        <header className="max-w-2xl border-b border-(--ui-stroke-tertiary) pb-6">
          <div className="mb-3 flex size-8 items-center justify-center rounded-[4px] bg-(--ui-bg-tertiary) text-(--ui-text-secondary)">
            <Codicon name="symbol-color" size="1.1rem" />
          </div>
          <h1 className="text-lg font-semibold tracking-[-0.015em] text-(--ui-text-primary)">{d.title}</h1>
          <p className="mt-1.5 max-w-xl text-xs leading-5 text-(--ui-text-secondary)">{d.subtitle}</p>
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
                <label className="mb-2 block text-xs font-medium text-(--ui-text-primary)" htmlFor="design-deliverable">
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
                <Select onValueChange={value => setSystem(value as DesignSystemPreset)} value={system}>
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
          </aside>
        </div>
      </div>
    </section>
  )
}
