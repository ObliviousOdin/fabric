import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import type { ReactNode } from "react";
import { Check, RefreshCw, ShieldCheck, Trash2, Users, X } from "lucide-react";
import { Badge } from "@/components/fabric/Badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { api } from "@/lib/api";
import type { PairingResponse, PairingUser } from "@/lib/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { Toast } from "@nous-research/ui/ui/components/toast";
import {
  CapabilityRow,
  EmptyState,
  PageToolbar,
  Skeleton,
  sourceIcon,
} from "@/components/ui";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useI18n } from "@/i18n";

function getUserKey(user: PairingUser): string {
  return `${user.platform}:${user.user_id}`;
}

function splitUserKey(key: string): { platform: string; user_id: string } {
  const idx = key.indexOf(":");
  if (idx === -1) return { platform: "", user_id: key };
  return { platform: key.slice(0, idx), user_id: key.slice(idx + 1) };
}

function getUserLabel(user: PairingUser): string {
  return user.user_name || user.user_id;
}

/** Meta segments joined by a mono `·` (the shared CapabilityRow idiom). */
function joinMeta(segments: ReactNode[]): ReactNode[] {
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
}

export default function PairingPage() {
  const [pending, setPending] = useState<PairingUser[]>([]);
  const [approved, setApproved] = useState<PairingUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [approving, setApproving] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();
  const { t } = useI18n();

  const loadPairing = useCallback(() => {
    setRefreshing(true);
    api
      .getPairing()
      .then((res: PairingResponse) => {
        setPending(res.pending);
        setApproved(res.approved);
        setLoadError(false);
      })
      .catch(() => {
        setLoadError(true);
        showToast(
          t.pairing?.loadFailed ?? "Failed to load pairing requests",
          "error",
        );
      })
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
    // t is stable per-locale; the toast copy re-resolves on the next call.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showToast]);

  useEffect(() => {
    // Existing dashboard data pages fetch from effects; keep this local and
    // explicit until the shared lint profile is updated for async page
    // loaders (same note as FilesPage).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadPairing();
  }, [loadPairing]);

  const handleApprove = async (user: PairingUser) => {
    if (!user.code) {
      showToast("Missing pairing code", "error");
      return;
    }
    const key = getUserKey(user);
    setApproving(key);
    try {
      await api.approvePairing(user.platform, user.code);
      showToast(`Approved: "${getUserLabel(user)}"`, "success");
      loadPairing();
    } catch (e) {
      showToast(`Error: ${e}`, "error");
    } finally {
      setApproving(null);
    }
  };

  const handleClearPending = async () => {
    setClearing(true);
    try {
      const res = await api.clearPendingPairing();
      setClearConfirmOpen(false);
      showToast(`Cleared ${res.cleared} pending request(s)`, "success");
      loadPairing();
    } catch (e) {
      showToast(`Error: ${e}`, "error");
    } finally {
      setClearing(false);
    }
  };

  const userRevoke = useConfirmDelete({
    onDelete: useCallback(
      async (key: string) => {
        const { platform, user_id } = splitUserKey(key);
        const user = approved.find((u) => getUserKey(u) === key);
        try {
          await api.revokePairing(platform, user_id);
          showToast(
            `Revoked: "${user ? getUserLabel(user) : user_id}"`,
            "success",
          );
          loadPairing();
        } catch (e) {
          showToast(`Error: ${e}`, "error");
          throw e;
        }
      },
      [approved, loadPairing, showToast],
    ),
  });

  // Header actions: explicit Refresh (the list is fetch-on-demand — no
  // polling, CN11) + Clear pending (opens the ConfirmDialog).
  useLayoutEffect(() => {
    setEnd(
      <PageToolbar
        label="Pairing actions"
        actions={
          <>
            <Button
              ghost
              size="icon"
              type="button"
              onClick={loadPairing}
              disabled={refreshing}
              aria-label={t.common.refresh}
              title={t.common.refresh}
            >
              {refreshing ? <Spinner /> : <RefreshCw />}
            </Button>
            <Button
              className="uppercase"
              size="sm"
              onClick={() => setClearConfirmOpen(true)}
              disabled={clearing}
              prefix={clearing ? <Spinner /> : <Trash2 className="h-4 w-4" />}
            >
              {t.pairing?.clearPending ?? "Clear pending"}
            </Button>
          </>
        }
      />,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, clearing, refreshing, loadPairing, t]);

  const pendingRevokeUser = userRevoke.pendingId
    ? approved.find((u) => getUserKey(u) === userRevoke.pendingId)
    : null;

  const pendingHeading = t.pairing?.pendingHeading ?? "Pending requests";
  const approvedHeading = t.pairing?.approvedHeading ?? "Approved users";

  if (loading) {
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        <div className="flex flex-col gap-3">
          <H2
            variant="sm"
            className="flex items-center gap-2 text-muted-foreground"
          >
            <Users className="h-4 w-4" />
            {pendingHeading}
          </H2>
          <Skeleton variant="row-list" rows={3} />
        </div>
        <div className="flex flex-col gap-3">
          <H2
            variant="sm"
            className="flex items-center gap-2 text-muted-foreground"
          >
            <ShieldCheck className="h-4 w-4" />
            {approvedHeading}
          </H2>
          <Skeleton variant="row-list" rows={3} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      <ConfirmDialog
        open={clearConfirmOpen}
        destructive
        title={
          t.pairing?.clearPendingConfirm ??
          "Clear all pending pairing requests?"
        }
        confirmLabel={t.common.clear}
        loading={clearing}
        onCancel={() => setClearConfirmOpen(false)}
        onConfirm={() => void handleClearPending()}
      />

      <DeleteConfirmDialog
        open={userRevoke.isOpen}
        onCancel={userRevoke.cancel}
        onConfirm={userRevoke.confirm}
        title="Revoke access"
        description={
          pendingRevokeUser
            ? `"${getUserLabel(pendingRevokeUser)}" will lose access. This cannot be undone.`
            : "This user will lose access. This cannot be undone."
        }
        confirmLabel="Revoke"
        loading={userRevoke.isDeleting}
      />

      {loadError && (
        <div className="flex flex-wrap items-center justify-between gap-2 border border-destructive/40 bg-destructive/10 px-3 py-2">
          <p className="text-xs text-destructive">
            {t.pairing?.loadFailed ?? "Failed to load pairing requests"}
          </p>
          <Button outlined size="xs" onClick={loadPairing}>
            {t.common.retry}
          </Button>
        </div>
      )}

      {/* Pending requests */}
      <div className="flex flex-col gap-3">
        <H2
          variant="sm"
          className="flex items-center gap-2 text-muted-foreground"
        >
          <Users className="h-4 w-4" />
          {pendingHeading} ({pending.length})
        </H2>

        {pending.length === 0 ? (
          <div className="border border-border">
            <EmptyState
              icon={Users}
              title={t.pairing?.noPendingTitle ?? "No pending pairing requests"}
              description={
                t.pairing?.noPendingDescription ??
                "Pairing codes appear here when an unapproved user messages the agent on a connected channel"
              }
            />
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {pending.map((user) => {
              const key = getUserKey(user);
              // R27: the served `code` is a reference (first 8 hex of the
              // code hash) — legacy rows serve "legacy" and cannot be
              // approved from the UI; never send that string.
              const approvable = Boolean(user.code) && user.code !== "legacy";
              const metaSegments: ReactNode[] = [];
              if (user.user_name) {
                metaSegments.push(
                  <span key="id" className="truncate" title={user.user_id}>
                    {user.user_id}
                  </span>,
                );
              }
              if (user.code) {
                metaSegments.push(
                  <span
                    key="code"
                    title="Code reference — the first 8 characters of the pairing code hash, not the code itself"
                  >
                    {user.code}
                  </span>,
                );
              }
              if (typeof user.age_minutes === "number") {
                metaSegments.push(
                  <span key="age">{user.age_minutes}m ago</span>,
                );
              }
              return (
                <CapabilityRow
                  key={key}
                  name={getUserLabel(user)}
                  mono={!user.user_name}
                  icon={sourceIcon(user.platform)}
                  badges={<Badge tone="outline">{user.platform}</Badge>}
                  meta={
                    metaSegments.length > 0 ? joinMeta(metaSegments) : undefined
                  }
                  actions={
                    <Button
                      size="sm"
                      className="uppercase"
                      onClick={() => void handleApprove(user)}
                      disabled={approving === key || !approvable}
                      title={
                        approvable
                          ? undefined
                          : "Legacy request without a code reference — it cannot be approved from here"
                      }
                      prefix={
                        approving === key ? (
                          <Spinner />
                        ) : (
                          <Check className="h-4 w-4" />
                        )
                      }
                    >
                      Approve
                    </Button>
                  }
                />
              );
            })}
          </div>
        )}
      </div>

      {/* Approved users */}
      <div className="flex flex-col gap-3">
        <H2
          variant="sm"
          className="flex items-center gap-2 text-muted-foreground"
        >
          <ShieldCheck className="h-4 w-4" />
          {approvedHeading} ({approved.length})
        </H2>

        {approved.length === 0 ? (
          <div className="border border-border">
            <EmptyState
              icon={ShieldCheck}
              title={t.pairing?.noApprovedTitle ?? "No approved users yet"}
              description={
                t.pairing?.noApprovedDescription ??
                "Approve a pending request to grant a user access to the agent"
              }
            />
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {approved.map((user) => {
              const key = getUserKey(user);
              return (
                <CapabilityRow
                  key={key}
                  name={user.user_id}
                  icon={sourceIcon(user.platform)}
                  badges={<Badge tone="outline">{user.platform}</Badge>}
                  description={user.user_name || undefined}
                  actions={
                    <Button
                      ghost
                      size="icon"
                      title="Revoke"
                      aria-label={`Revoke ${getUserLabel(user)}`}
                      className="text-destructive hover:text-destructive"
                      onClick={() => userRevoke.requestDelete(key)}
                    >
                      <X />
                    </Button>
                  }
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
