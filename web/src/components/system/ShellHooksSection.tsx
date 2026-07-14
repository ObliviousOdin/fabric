import { useCallback, useState, type ReactNode } from "react";
import { Plus, Terminal, Trash2, X } from "lucide-react";
import { Badge } from "@/components/fabric/Badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Checkbox } from "@nous-research/ui/ui/components/checkbox";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import {
  CAPABILITY_STATE_TONES,
  CapabilityRow,
  EmptyState,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { HookEntry, HooksResponse } from "@/lib/api";
import { cn, themedBody } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { SystemSection } from "./SystemSection";
import type { ShowToast } from "./format";

// Must match the backend hook registry (R28 drift watch) — used only when
// /api/ops/hooks doesn't serve `valid_events`.
const HOOK_EVENTS_FALLBACK = [
  "pre_tool_call",
  "post_tool_call",
  "pre_llm_call",
  "post_llm_call",
  "on_session_start",
  "on_session_end",
];

export interface ShellHooksSectionProps {
  hooks: HooksResponse | null;
  loading: boolean;
  showToast: ShowToast;
  reload: () => void;
}

/**
 * Shell hooks (Y10, CapabilityRow consumer #9): a hook is exactly a
 * capability — identity (mono command), state (allowed/not approved on the
 * CAP2 tones), provenance (event badge), actions (remove). The create
 * modal is a consent surface and stays frozen (approve-now checkbox + the
 * arbitrary-commands warning copy verbatim, CN9-class).
 */
export function ShellHooksSection({
  hooks,
  loading,
  showToast,
  reload,
}: ShellHooksSectionProps) {
  const { t } = useI18n();

  const [hookModalOpen, setHookModalOpen] = useState(false);
  const closeHookModal = useCallback(() => setHookModalOpen(false), []);
  const hookModalRef = useModalBehavior({
    open: hookModalOpen,
    onClose: closeHookModal,
  });
  const [hookEvent, setHookEvent] = useState("pre_tool_call");
  const [hookCommand, setHookCommand] = useState("");
  const [hookMatcher, setHookMatcher] = useState("");
  const [hookTimeout, setHookTimeout] = useState("");
  const [hookApprove, setHookApprove] = useState(true);
  const [creatingHook, setCreatingHook] = useState(false);

  const validEvents = hooks?.valid_events?.length
    ? hooks.valid_events
    : HOOK_EVENTS_FALLBACK;

  const createHook = async () => {
    if (!hookCommand.trim()) {
      showToast("Command is required", "error");
      return;
    }
    setCreatingHook(true);
    try {
      await api.createHook({
        event: hookEvent,
        command: hookCommand.trim(),
        matcher: hookMatcher.trim() || undefined,
        timeout: hookTimeout.trim() ? Number(hookTimeout) : undefined,
        approve: hookApprove,
      });
      showToast("Hook created", "success");
      setHookCommand("");
      setHookMatcher("");
      setHookTimeout("");
      setHookModalOpen(false);
      reload();
    } catch (e) {
      showToast(`Failed to create hook: ${e}`, "error");
    } finally {
      setCreatingHook(false);
    }
  };

  const hookDelete = useConfirmDelete({
    onDelete: useCallback(
      async (key: string) => {
        const sep = key.indexOf("|");
        const event = key.slice(0, sep);
        const command = key.slice(sep + 1);
        try {
          await api.deleteHook(event, command);
          showToast("Hook removed", "success");
          reload();
        } catch (e) {
          showToast(`Failed to remove hook: ${e}`, "error");
          throw e;
        }
      },
      [reload, showToast],
    ),
  });

  const newHookLabel = t.system?.newHook ?? "New hook";
  const newHookButton = (
    <Button
      size="sm"
      className="uppercase"
      prefix={<Plus className="h-3.5 w-3.5" />}
      onClick={() => setHookModalOpen(true)}
    >
      {newHookLabel}
    </Button>
  );

  const renderHookMeta = (h: HookEntry): ReactNode => {
    const segments: ReactNode[] = [];
    if (h.matcher) {
      segments.push(<span key="matcher">matcher: {h.matcher}</span>);
    }
    if (h.timeout != null) {
      segments.push(<span key="timeout">timeout {h.timeout}s</span>);
    }
    if (segments.length === 0) return undefined;
    return segments.flatMap((seg, i) =>
      i > 0
        ? [
            <span key={`sep-${i}`} aria-hidden="true">
              ·
            </span>,
            seg,
          ]
        : [seg],
    );
  };

  return (
    <SystemSection
      icon={Terminal}
      title={t.system?.shellHooks ?? "Shell hooks"}
      end={newHookButton}
      loading={loading}
    >
      <DeleteConfirmDialog
        open={hookDelete.isOpen}
        onCancel={hookDelete.cancel}
        onConfirm={hookDelete.confirm}
        title="Remove shell hook"
        description="Remove this hook from config and revoke its consent? It stops firing on the next restart."
        loading={hookDelete.isDeleting}
      />

      {/* Create-hook modal (frozen consent surface, Y10/CN9) */}
      {hookModalOpen && (
        <div
          ref={hookModalRef}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
          onClick={(e) => e.target === e.currentTarget && setHookModalOpen(false)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className={cn(
              themedBody,
              "relative w-full max-w-lg border border-border bg-card shadow-2xl flex flex-col",
            )}
          >
            <Button
              ghost
              size="icon"
              onClick={() => setHookModalOpen(false)}
              className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X />
            </Button>
            <header className="p-5 pb-3 border-b border-border">
              <h2 className="font-mondwest text-display text-base tracking-wider">
                New shell hook
              </h2>
            </header>
            <div className="p-5 grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="hook-event">Event</Label>
                <Select
                  id="hook-event"
                  value={hookEvent}
                  onValueChange={(v) => setHookEvent(v)}
                >
                  {validEvents.map((ev) => (
                    <SelectOption key={ev} value={ev}>
                      {ev}
                    </SelectOption>
                  ))}
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="hook-command">Command (absolute path)</Label>
                <Input
                  id="hook-command"
                  autoFocus
                  placeholder="/usr/local/bin/my-hook.sh"
                  value={hookCommand}
                  onChange={(e) => setHookCommand(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="hook-matcher">Matcher (optional)</Label>
                  <Input
                    id="hook-matcher"
                    placeholder="e.g. terminal"
                    value={hookMatcher}
                    onChange={(e) => setHookMatcher(e.target.value)}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="hook-timeout">Timeout (s)</Label>
                  <Input
                    id="hook-timeout"
                    placeholder="10"
                    value={hookTimeout}
                    onChange={(e) => setHookTimeout(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex items-center gap-2.5">
                <Checkbox
                  checked={hookApprove}
                  id="hook-approve"
                  onCheckedChange={(checked) => setHookApprove(checked === true)}
                />

                <Label
                  className="cursor-pointer text-sm font-normal normal-case tracking-normal text-muted-foreground"
                  htmlFor="hook-approve"
                >
                  Approve now (grant consent so it fires; otherwise it stays
                  configured but inactive)
                </Label>
              </div>
              <p className="text-xs text-warning">
                Shell hooks run arbitrary commands on this host. Only add scripts
                you trust. Takes effect on the next gateway/session restart.
              </p>
              <div className="flex justify-end">
                <Button
                  className="uppercase"
                  size="sm"
                  onClick={createHook}
                  disabled={creatingHook}
                  prefix={creatingHook ? <Spinner /> : undefined}
                >
                  {creatingHook ? "Creating" : "Create hook"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {!hooks || hooks.hooks.length === 0 ? (
        <EmptyState
          icon={Terminal}
          title={t.system?.noHooksTitle ?? "No shell hooks configured"}
          description={
            t.system?.noHooksDescription ??
            "Hooks run trusted scripts on gateway and session events."
          }
          action={
            <Button
              size="sm"
              className="uppercase"
              prefix={<Plus className="h-3.5 w-3.5" />}
              onClick={() => setHookModalOpen(true)}
            >
              {newHookLabel}
            </Button>
          }
          className="border border-border"
        />
      ) : (
        <div className="flex flex-col gap-2">
          {hooks.hooks.map((h: HookEntry, i) => (
            <CapabilityRow
              key={`${h.event}-${i}`}
              name={h.command ?? ""}
              badges={
                <>
                  <Badge tone="outline">{h.event}</Badge>
                  {h.executable === false && (
                    <Badge tone="destructive">not executable</Badge>
                  )}
                  {/* Consent state on the CAP2 tones (allowed=success,
                      not approved=warning — the kept tone pair). */}
                  <Badge
                    tone={
                      h.allowed
                        ? CAPABILITY_STATE_TONES.enabled
                        : CAPABILITY_STATE_TONES["needs-setup"]
                    }
                  >
                    {h.allowed ? "allowed" : "not approved"}
                  </Badge>
                </>
              }
              meta={renderHookMeta(h)}
              actions={
                <Button
                  ghost
                  size="icon"
                  className="text-destructive"
                  aria-label="Remove hook"
                  onClick={() =>
                    hookDelete.requestDelete(`${h.event}|${h.command ?? ""}`)
                  }
                >
                  <Trash2 />
                </Button>
              }
            />
          ))}
        </div>
      )}
    </SystemSection>
  );
}
