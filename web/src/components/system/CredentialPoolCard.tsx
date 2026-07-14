import { useCallback, useState } from "react";
import { Trash2 } from "lucide-react";
import { Badge } from "@/components/fabric/Badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { api } from "@/lib/api";
import type { CredentialPoolProvider } from "@/lib/api";
import type { ShowToast } from "./format";

export interface CredentialPoolCardProps {
  pool: CredentialPoolProvider[];
  showToast: ShowToast;
  reload: () => void;
}

/**
 * Credential-pool card (Y5, frozen behavior): add form (provider/key/label
 * with required check), per-provider groups, 1px entry rows (label · mono
 * `token_preview` · `auth_type` outline · `last_status` chip), remove
 * confirm keyed `provider|index`. No reveal exists for pooled keys and
 * none is added (CN9).
 */
export function CredentialPoolCard({
  pool,
  showToast,
  reload,
}: CredentialPoolCardProps) {
  const [credProvider, setCredProvider] = useState("openrouter");
  const [credKey, setCredKey] = useState("");
  const [credLabel, setCredLabel] = useState("");
  const [addingCred, setAddingCred] = useState(false);

  const addCredential = async () => {
    if (!credProvider.trim() || !credKey.trim()) {
      showToast("Provider and API key required", "error");
      return;
    }
    setAddingCred(true);
    try {
      await api.addCredentialPoolEntry(
        credProvider.trim(),
        credKey.trim(),
        credLabel.trim() || undefined,
      );
      showToast("Credential added", "success");
      setCredKey("");
      setCredLabel("");
      reload();
    } catch (e) {
      showToast(`Failed to add credential: ${e}`, "error");
    } finally {
      setAddingCred(false);
    }
  };

  const credDelete = useConfirmDelete({
    onDelete: useCallback(
      async (key: string) => {
        const [provider, idxStr] = key.split("|");
        try {
          await api.removeCredentialPoolEntry(provider, Number(idxStr));
          showToast("Credential removed", "success");
          reload();
        } catch (e) {
          showToast(`Failed to remove: ${e}`, "error");
          throw e;
        }
      },
      [reload, showToast],
    ),
  });

  return (
    <Card>
      <DeleteConfirmDialog
        open={credDelete.isOpen}
        onCancel={credDelete.cancel}
        onConfirm={credDelete.confirm}
        title="Remove credential"
        description="Remove this pooled API key? The agent will no longer rotate through it."
        loading={credDelete.isDeleting}
      />
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <div className="grid gap-2">
            <Label htmlFor="cred-provider">Provider</Label>
            <Input
              id="cred-provider"
              value={credProvider}
              onChange={(e) => setCredProvider(e.target.value)}
              placeholder="openrouter"
            />
          </div>
          <div className="grid gap-2 sm:col-span-2">
            <Label htmlFor="cred-key">API key</Label>
            <Input
              id="cred-key"
              type="password"
              value={credKey}
              onChange={(e) => setCredKey(e.target.value)}
              placeholder="sk-…"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="cred-label">Label</Label>
            <Input
              id="cred-label"
              value={credLabel}
              onChange={(e) => setCredLabel(e.target.value)}
              placeholder="optional"
            />
          </div>
        </div>
        <div className="flex justify-end">
          <Button
            size="sm"
            className="uppercase"
            onClick={addCredential}
            disabled={addingCred}
            prefix={addingCred ? <Spinner /> : undefined}
          >
            Add key
          </Button>
        </div>
        {pool.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No pooled credentials. Add one above to enable key rotation.
          </p>
        )}
        {pool.map((prov) => (
          <div key={prov.provider} className="flex flex-col gap-2">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">
              {prov.provider}
            </span>
            {prov.entries.map((entry) => (
              <div
                key={`${prov.provider}-${entry.index}`}
                className="flex items-center gap-3 border border-border bg-background/40 px-3 py-2"
              >
                <span className="text-sm font-medium">{entry.label}</span>
                <span className="font-mono-ui text-xs text-muted-foreground">
                  {entry.token_preview}
                </span>
                <Badge tone="outline">{entry.auth_type}</Badge>
                {entry.last_status && (
                  <Badge tone="secondary">{entry.last_status}</Badge>
                )}
                <Button
                  ghost
                  size="icon"
                  className="ml-auto text-destructive"
                  aria-label="Remove credential"
                  onClick={() =>
                    credDelete.requestDelete(`${prov.provider}|${entry.index}`)
                  }
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
