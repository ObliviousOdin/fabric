'use client'

import { useStore } from '@nanostores/react'
import { type FC, useCallback, useEffect, useId, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useI18n } from '@/i18n'
import { humanizeApprovalReason, isDestructiveApproval, isHighRiskApproval } from '@/lib/approval-details'
import { triggerHaptic } from '@/lib/haptics'
import { AlertCircle, AlertTriangle, ChevronDown, Loader2 } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $gateway } from '@/store/gateway'
import { notifyError } from '@/store/notifications'
import {
  $approvalInlineVisible,
  $approvalRequest,
  type ApprovalRequest,
  clearApprovalRequest,
  registerApprovalInlineAnchor
} from '@/store/prompts'
import { $currentCwd } from '@/store/session'

import type { ToolPart } from './fallback-model'

// Inline approval control. Rendered as a compact button strip
// under the pending tool row that raised the approval (the row already shows
// the command, so the strip deliberately doesn't repeat it) instead of as a
// modal overlay.
//
// Binding is POSITIONAL, not command-matched: the desktop `tool.start` payload
// carries no structured args (only tool_id/name/context — see
// tui_gateway/server.py::_on_tool_start), so we cannot join the approval to the
// row by command string. But `approval.request` only ever fires from the
// `terminal` / `execute_code` guards and the agent thread blocks on exactly one
// approval at a time, so the single pending row of those tools IS the row that
// raised it. The command/description text comes from `$approvalRequest` (the
// event payload), which is the only place that data reliably exists.
export const APPROVAL_TOOLS = new Set(['terminal', 'execute_code'])

// Canonical gateway choices (ui-tui/src/components/prompts.tsx).
type ApprovalChoice = 'once' | 'session' | 'always' | 'deny'

// Remount the bar when the *logical* approval changes so per-request state
// (notably the auto-open-for-high-risk default) re-initializes. Keyed by
// content, not object identity: the persistent floating fallback swaps
// `request` across sessions without unmounting, and a reconnect can hand us a
// fresh object for the same approval — keying on session+command re-fires the
// risk default on a genuinely new approval while preserving a manual
// expand/collapse within one.
const approvalBarKey = (request: ApprovalRequest): string => `${request.sessionId ?? ''}:${request.command}`

export const PendingToolApproval: FC<{ part: ToolPart }> = ({ part }) => {
  const request = useStore($approvalRequest)

  if (!request || !APPROVAL_TOOLS.has(part.toolName)) {
    return null
  }

  return <InlineApprovalBar request={request} toolName={part.toolName} />
}

const InlineApprovalBar: FC<{ request: ApprovalRequest; toolName?: string }> = ({ request, toolName }) => {
  useEffect(() => registerApprovalInlineAnchor(), [])

  return <ApprovalBar key={approvalBarKey(request)} request={request} surface="inline" toolName={toolName} />
}

export const PendingApprovalFallback: FC = () => {
  const { t } = useI18n()
  const request = useStore($approvalRequest)
  const inlineVisible = useStore($approvalInlineVisible)

  if (!request || inlineVisible) {
    return null
  }

  return (
    <div
      className="pointer-events-none absolute left-1/2 z-30 w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2"
      data-slot="tool-approval-fallback"
      style={{ bottom: 'calc(var(--composer-measured-height) + var(--status-stack-measured-height) + 0.875rem)' }}
    >
      <div className="pointer-events-auto rounded-xl border border-primary/30 bg-(--ui-chat-surface-background) px-3 py-2 shadow-lg backdrop-blur-xl [-webkit-backdrop-filter:blur(1rem)]">
        <div className="flex min-w-0 items-center gap-2 text-sm text-primary">
          <AlertCircle className="size-4 shrink-0" />
          <span className="shrink-0 font-medium">{t.assistant.approval.jumpToApproval}</span>
          {request.description && (
            <span className="min-w-0 truncate text-(--ui-text-tertiary)">{request.description}</span>
          )}
        </div>
        <ApprovalBar key={approvalBarKey(request)} request={request} surface="floating" />
      </div>
    </div>
  )
}

const isMac = typeof navigator !== 'undefined' && /Mac|iP(hone|ad|od)/.test(navigator.platform)

// One labelled field inside the details panel. The value wraps rather than
// truncating so a long warning or path is always readable in full.
const ApprovalDetailRow: FC<{ label: string; mono?: boolean; value: string }> = ({ label, mono, value }) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-(--ui-text-tertiary)">{label}</span>
    <span className={cn('whitespace-pre-wrap break-words text-foreground', mono && 'font-mono')}>{value}</span>
  </div>
)

const ApprovalBar: FC<{ request: ApprovalRequest; surface: 'floating' | 'inline'; toolName?: string }> = ({
  request,
  surface,
  toolName
}) => {
  const { t } = useI18n()
  const copy = t.assistant.approval
  const gateway = useStore($gateway)
  const cwd = useStore($currentCwd)
  const detailsId = useId()
  const [submitting, setSubmitting] = useState<ApprovalChoice | null>(null)
  // "Always allow" persists the pattern to ~/.fabric/config.yaml permanently, so
  // it goes through a confirm step rather than firing straight from the menu.
  const [confirmAlways, setConfirmAlways] = useState(false)
  // Controlled so the Esc→deny shortcut can stand down while the options menu is
  // open (otherwise Esc-to-close-the-menu would deny the whole approval).
  const [menuOpen, setMenuOpen] = useState(false)
  const busy = submitting !== null
  // false when the backend won't honor a permanent allow (tirith warning) → hide "Always allow".
  const allowPermanent = request.allowPermanent !== false
  const hasCommand = request.command.trim().length > 0

  // Derived, presentation-only context for the "Review approval details" panel
  // (issue #51). The pending tool row shows only a single truncated command
  // line, so this panel is where the full warning, command, tool, and working
  // directory live — nothing critical is silently truncated. High-risk
  // approvals (destructive, remote-exec, or a content-security finding that
  // blocks a permanent allow) open it automatically.
  const riskInput = useMemo(
    () => ({
      allowPermanent: request.allowPermanent,
      command: request.command,
      description: request.description,
      patternKey: request.patternKey,
      patternKeys: request.patternKeys
    }),
    [request.allowPermanent, request.command, request.description, request.patternKey, request.patternKeys]
  )

  const reason = useMemo(
    () => humanizeApprovalReason(request.patternKey, request.description),
    [request.patternKey, request.description]
  )

  const destructive = useMemo(() => isDestructiveApproval(riskInput), [riskInput])
  const highRisk = useMemo(() => isHighRiskApproval(riskInput), [riskInput])
  const [showDetails, setShowDetails] = useState(highRisk)

  const respond = useCallback(
    async (choice: ApprovalChoice) => {
      // Another bar (or the keyboard path) may have already resolved this
      // approval; the atom is the single source of truth, so bail if it's gone.
      if (busy || !$approvalRequest.get()) {
        return
      }

      if (!gateway) {
        notifyError(new Error(copy.gatewayDisconnected), copy.sendFailed)

        return
      }

      setSubmitting(choice)

      try {
        await gateway.request<{ resolved?: boolean }>('approval.respond', {
          choice,
          session_id: request.sessionId ?? undefined
        })
        triggerHaptic(choice === 'deny' ? 'cancel' : 'submit')
        clearApprovalRequest(request.sessionId)
      } catch (error) {
        notifyError(error, copy.sendFailed)
        setSubmitting(null)
      }
    },
    [busy, copy.gatewayDisconnected, copy.sendFailed, gateway, request.sessionId]
  )

  // ⌘/Ctrl+Enter → Run, Esc → Reject.
  // While the confirm dialog or the options menu is open, that surface owns the
  // keyboard (Esc closes it), so the strip-level shortcuts stand down to avoid
  // denying the whole approval when the user just meant to back out.
  useEffect(() => {
    if (confirmAlways || menuOpen) {
      return
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        void respond('once')
      } else if (event.key === 'Escape') {
        event.preventDefault()
        void respond('deny')
      }
    }

    window.addEventListener('keydown', onKeyDown, true)

    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [confirmAlways, menuOpen, respond])

  return (
    <div
      className={cn(surface === 'inline' ? 'mt-1 ps-5' : 'mt-2')}
      data-slot={surface === 'inline' ? 'tool-approval-inline' : 'tool-approval-actions'}
    >
      <div className="flex items-center gap-2.5">
        <div className="inline-flex h-6 items-stretch overflow-hidden rounded-md border border-primary/25 bg-primary/10 text-primary">
          <Button
            className="h-full gap-1 rounded-none px-2 text-xs font-medium text-primary hover:bg-primary/15 hover:text-primary"
            disabled={busy}
            onClick={() => void respond('once')}
            size="xs"
            variant="ghost"
          >
            {submitting === 'once' ? <Loader2 className="size-3 animate-spin" /> : copy.run}
            {submitting !== 'once' && <span className="text-[0.625rem] text-primary/60">{isMac ? '⌘⏎' : 'Ctrl⏎'}</span>}
          </Button>
          <span aria-hidden className="w-px self-stretch bg-primary/20" />
          <DropdownMenu onOpenChange={setMenuOpen} open={menuOpen}>
            <DropdownMenuTrigger asChild>
              <Button
                aria-label={copy.moreOptions}
                className="h-full w-5 rounded-none px-0 text-primary hover:bg-primary/15 hover:text-primary"
                disabled={busy}
                size="xs"
                variant="ghost"
              >
                <ChevronDown className="size-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-44">
              <DropdownMenuItem onSelect={() => void respond('session')}>{copy.allowSession}</DropdownMenuItem>
              {allowPermanent && (
                <DropdownMenuItem
                  onSelect={() => {
                    // Defer one tick so the menu fully unmounts before the dialog
                    // mounts — otherwise Radix's focus-return races the dialog and
                    // dismisses it via onInteractOutside.
                    setTimeout(() => setConfirmAlways(true), 0)
                  }}
                >
                  {copy.alwaysAllowMenu}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => void respond('deny')} variant="destructive">
                {copy.reject}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <Button
          className="h-6 gap-1.5 rounded-md px-1.5 text-xs font-normal text-(--ui-text-tertiary) hover:text-foreground"
          disabled={busy}
          onClick={() => void respond('deny')}
          size="xs"
          variant="ghost"
        >
          {submitting === 'deny' ? <Loader2 className="size-3 animate-spin" /> : copy.reject}
          {submitting !== 'deny' && <span className="text-[0.625rem] opacity-55">Esc</span>}
        </Button>

        <Button
          aria-controls={detailsId}
          aria-expanded={showDetails}
          aria-label={showDetails ? copy.detailsHide : copy.detailsShow}
          className="h-6 gap-1 rounded-md px-1.5 text-xs font-normal text-(--ui-text-tertiary) hover:text-foreground"
          onClick={() => setShowDetails(value => !value)}
          size="xs"
          variant="ghost"
        >
          {copy.detailsToggle}
          <ChevronDown className={cn('size-3 transition-transform', showDetails && 'rotate-180')} />
        </Button>
      </div>

      {showDetails && (
        <div
          aria-label={copy.detailsPanelLabel}
          className="mt-1.5 flex flex-col gap-2 rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-chat-surface-background) px-2.5 py-2 text-xs leading-snug"
          id={detailsId}
          role="region"
        >
          {destructive && (
            <div className="flex items-center gap-1.5 font-medium text-amber-600 dark:text-amber-400">
              <AlertTriangle className="size-3.5 shrink-0" />
              <span>{copy.destructiveBadge}</span>
            </div>
          )}

          <ApprovalDetailRow label={copy.detailsReason} value={reason} />
          {toolName && <ApprovalDetailRow label={copy.detailsTool} value={toolName} />}
          {cwd && <ApprovalDetailRow label={copy.detailsWorkingDir} mono value={cwd} />}

          {hasCommand && (
            <div className="flex flex-col gap-1">
              <span className="text-(--ui-text-tertiary)">{copy.command}</span>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded border border-(--ui-stroke-tertiary) bg-(--ui-chat-surface-background) px-2 py-1.5 font-mono text-xs leading-snug text-foreground">
                {request.command.trim()}
              </pre>
            </div>
          )}
        </div>
      )}

      <Dialog onOpenChange={setConfirmAlways} open={confirmAlways}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{copy.alwaysTitle}</DialogTitle>
            <DialogDescription>{copy.alwaysDescription(request.description)}</DialogDescription>
          </DialogHeader>

          {request.command.trim() && (
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-chat-surface-background) px-2.5 py-1.5 font-mono text-xs leading-snug text-foreground">
              {request.command.trim()}
            </pre>
          )}

          <DialogFooter>
            <Button onClick={() => setConfirmAlways(false)} size="sm" variant="ghost">
              {t.common.cancel}
            </Button>
            <Button
              onClick={() => {
                setConfirmAlways(false)
                void respond('always')
              }}
              size="sm"
              variant="destructive"
            >
              {copy.alwaysAllow}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
