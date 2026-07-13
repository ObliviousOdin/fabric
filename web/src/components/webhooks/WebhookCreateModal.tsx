import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { api } from "@/lib/api";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { cn, themedBody } from "@/lib/utils";
import { CopyButton } from "./CopyButton";

interface CreatedWebhook {
  url: string;
  secret: string;
}

export interface WebhookCreateModalProps {
  open: boolean;
  onClose: () => void;
  /** Reload the subscriptions list after a successful create. */
  onCreated: () => void;
  showToast: (message: string, type: "success" | "error") => void;
}

/**
 * New-subscription modal (W3 — flow frozen): name required client-side,
 * events CSV → list, deliver select, deliver-only checkbox, prompt
 * textarea, server 400s surfaced via toast (incl. the deliver_only+log
 * rejection), then the secret-once panel — URL row + warning-tinted
 * secret row + copy buttons + "only shown once" copy (CN9: the consent
 * moment is never redesigned). Form resets on create; the secret is gone
 * once the modal closes.
 */
export function WebhookCreateModal({
  open,
  onClose,
  onCreated,
  showToast,
}: WebhookCreateModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [events, setEvents] = useState("");
  const [deliver, setDeliver] = useState("log");
  const [deliverOnly, setDeliverOnly] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedWebhook | null>(null);

  const modalRef = useModalBehavior({ open, onClose });

  // Closing drops the secret from state immediately, so a reopened modal
  // always starts from the form — a previously shown secret never
  // reappears (shown-once semantics, CN9).
  useEffect(() => {
    if (!open) setCreated(null);
  }, [open]);

  const handleCreate = async () => {
    if (!name.trim()) {
      showToast("Name required", "error");
      return;
    }
    setCreating(true);
    try {
      const eventsList = events
        .split(",")
        .map((e) => e.trim())
        .filter(Boolean);
      const res = await api.createWebhook({
        name: name.trim(),
        description: description.trim() || undefined,
        events: eventsList.length ? eventsList : undefined,
        deliver,
        deliver_only: deliverOnly,
        prompt: prompt.trim() || undefined,
      });
      showToast("Created ✓", "success");
      setCreated({ url: res.url, secret: res.secret });
      setName("");
      setDescription("");
      setEvents("");
      setDeliver("log");
      setDeliverOnly(false);
      setPrompt("");
      onCreated();
    } catch (e) {
      showToast(`Failed to create: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  if (!open) return null;

  return (
    <div
      ref={modalRef}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-webhook-title"
    >
      <div className={cn(themedBody, "relative w-full max-w-lg border border-border bg-card shadow-2xl flex flex-col max-h-[90vh] overflow-y-auto")}>
        <Button
          ghost
          size="icon"
          onClick={onClose}
          className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
          aria-label="Close"
        >
          <X />
        </Button>

        <header className="p-5 pb-3 border-b border-border">
          <h2
            id="create-webhook-title"
            className="font-mondwest text-display text-base tracking-wider"
          >
            New subscription
          </h2>
        </header>

        {created ? (
          <div className="p-5 grid gap-4">
            <p className="text-sm text-muted-foreground">
              Subscription created. Copy the secret now — it is only shown
              once.
            </p>

            <div className="grid gap-2">
              <Label>Webhook URL</Label>
              <div className="flex items-center gap-2 border border-border bg-background/40 px-3 py-2">
                <span className="flex-1 min-w-0 truncate font-mono text-xs">
                  {created.url}
                </span>
                <CopyButton value={created.url} />
              </div>
            </div>

            <div className="grid gap-2">
              <Label>Secret (shown once)</Label>
              <div className="flex items-center gap-2 border border-warning/40 bg-warning/10 px-3 py-2">
                <span className="flex-1 min-w-0 truncate font-mono text-xs">
                  {created.secret}
                </span>
                <CopyButton value={created.secret} />
              </div>
            </div>

            <div className="flex justify-end">
              <Button className="uppercase" size="sm" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <div className="p-5 grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="webhook-name">Name</Label>
              <Input
                id="webhook-name"
                autoFocus
                placeholder="e.g. github-push"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="webhook-description">Description</Label>
              <Input
                id="webhook-description"
                placeholder="What this webhook does (optional)"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="webhook-events">Events</Label>
              <Input
                id="webhook-events"
                placeholder="comma-separated, leave empty for all"
                value={events}
                onChange={(e) => setEvents(e.target.value)}
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="webhook-deliver">Deliver to</Label>
                <Select
                  id="webhook-deliver"
                  value={deliver}
                  onValueChange={(v) => setDeliver(v)}
                >
                  <SelectOption value="log">Log</SelectOption>
                  <SelectOption value="telegram">Telegram</SelectOption>
                  <SelectOption value="discord">Discord</SelectOption>
                  <SelectOption value="slack">Slack</SelectOption>
                  <SelectOption value="email">Email</SelectOption>
                  <SelectOption value="github_comment">
                    GitHub comment
                  </SelectOption>
                </Select>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="webhook-deliver-only">Deliver only</Label>
                <label className="flex items-center gap-2 text-sm text-muted-foreground h-9">
                  <input
                    id="webhook-deliver-only"
                    type="checkbox"
                    checked={deliverOnly}
                    onChange={(e) => setDeliverOnly(e.target.checked)}
                  />
                  Skip the agent, deliver payload directly
                </label>
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="webhook-prompt">Prompt</Label>
              <textarea
                id="webhook-prompt"
                className="flex min-h-[80px] w-full border border-border bg-background/40 px-3 py-2 text-sm font-courier shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30 focus-visible:border-foreground/25"
                placeholder="Instructions for the agent when this webhook fires (optional)"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </div>

            <div className="flex justify-end">
              <Button
                className="uppercase"
                size="sm"
                onClick={handleCreate}
                disabled={creating}
                prefix={creating ? <Spinner /> : undefined}
              >
                {creating ? "Creating…" : "Create"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
