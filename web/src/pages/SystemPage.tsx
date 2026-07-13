import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Brain,
  Database,
  Globe,
  KeyRound,
  Power,
  Server,
  Sparkles,
} from "lucide-react";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { EgressStatusCard } from "@/components/EgressStatusCard";
import { Skeleton } from "@/components/ui";
import { ActionLogViewer } from "@/components/system/ActionLogViewer";
import { SystemSection } from "@/components/system/SystemSection";
import { HostCard } from "@/components/system/HostCard";
import { GatewayCard } from "@/components/system/GatewayCard";
import { CuratorCard } from "@/components/system/CuratorCard";
import { PortalCard } from "@/components/system/PortalCard";
import { MemoryCard } from "@/components/system/MemoryCard";
import { CredentialPoolCard } from "@/components/system/CredentialPoolCard";
import { OperationsCard } from "@/components/system/OperationsCard";
import {
  BackupRestoreCard,
  type ActionCompletion,
} from "@/components/system/BackupRestoreCard";
import { DebugShareCard } from "@/components/system/DebugShareCard";
import { CheckpointsCard } from "@/components/system/CheckpointsCard";
import { ShellHooksSection } from "@/components/system/ShellHooksSection";
import { api } from "@/lib/api";
import type {
  StatusResponse,
  MemoryStatus,
  CredentialPoolProvider,
  CheckpointsResponse,
  HooksResponse,
  SystemStats,
  UpdateCheckResponse,
  CuratorStatus,
  PortalStatus,
} from "@/lib/api";
import { useI18n } from "@/i18n";

/** One key per independent fetch — sections skeleton off their own fetch
 *  settling, never the batch (Y14/R29). */
type SectionKey =
  | "status"
  | "stats"
  | "memory"
  | "pool"
  | "checkpoints"
  | "hooks"
  | "curator"
  | "portal"
  | "update";

const UNSETTLED: Record<SectionKey, boolean> = {
  status: false,
  stats: false,
  memory: false,
  pool: false,
  checkpoints: false,
  hooks: false,
  curator: false,
  portal: false,
  update: false,
};

/**
 * SYSTEM — the operator's console (Y1): Host → Gateway → Network & AI
 * egress → Portal → Curator → Memory → Credential pool → Operations →
 * Checkpoints → Shell hooks. The section cards live in
 * `components/system/`; this page owns the fan-out fetches, the shared
 * action-log viewer (CN10, pinned above all sections while an action
 * runs), and the gateway verbs.
 */
export default function SystemPage() {
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const ts = t.system;

  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [memory, setMemory] = useState<MemoryStatus | null>(null);
  const [pool, setPool] = useState<CredentialPoolProvider[]>([]);
  const [checkpoints, setCheckpoints] = useState<CheckpointsResponse | null>(
    null,
  );
  const [hooks, setHooks] = useState<HooksResponse | null>(null);
  const [curator, setCurator] = useState<CuratorStatus | null>(null);
  const [portal, setPortal] = useState<PortalStatus | null>(null);
  const [updateInfo, setUpdateInfo] = useState<UpdateCheckResponse | null>(
    null,
  );
  // First-load-only skeleton gates: once a fetch has settled its section
  // never skeletons again — background refreshes keep the live layout (G13).
  const [settled, setSettled] = useState<Record<SectionKey, boolean>>(
    UNSETTLED,
  );

  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [lastCompletion, setLastCompletion] =
    useState<ActionCompletion | null>(null);
  const completionSeq = useRef(0);

  const settle = useCallback((key: SectionKey) => {
    setSettled((prev) => (prev[key] ? prev : { ...prev, [key]: true }));
  }, []);

  const loadAll = useCallback(() => {
    // Each fetch resolves and settles its own section (Y14/R29): the
    // slowest endpoint (the network-bound update check) must never blank
    // the whole console, and a failed portal fetch skeleton→hides only
    // the Portal card.
    void api
      .getStatus()
      .then(setStatus)
      .catch(() => undefined)
      .finally(() => settle("status"));
    void api
      .getSystemStats()
      .then(setStats)
      .catch(() => undefined)
      .finally(() => settle("stats"));
    void api
      .getMemory()
      .then(setMemory)
      .catch(() => undefined)
      .finally(() => settle("memory"));
    void api
      .getCredentialPool()
      .then((p) => setPool(p.providers))
      .catch(() => undefined)
      .finally(() => settle("pool"));
    void api
      .getCheckpoints()
      .then(setCheckpoints)
      .catch(() => undefined)
      .finally(() => settle("checkpoints"));
    void api
      .getHooks()
      .then(setHooks)
      .catch(() => undefined)
      .finally(() => settle("hooks"));
    void api
      .getCurator()
      .then(setCurator)
      .catch(() => undefined)
      .finally(() => settle("curator"));
    void api
      .getPortal()
      .then(setPortal)
      .catch(() => undefined)
      .finally(() => settle("portal"));
    // Cached (non-forced) check so the version row shows update status on
    // load without a separate effect / a forced network round-trip.
    void api
      .checkHermesUpdate(false)
      .then(setUpdateInfo)
      .catch(() => undefined)
      .finally(() => settle("update"));
  }, [settle]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // ── Gateway lifecycle (Y2, frozen) ─────────────────────────────────
  const runGateway = useCallback(
    async (verb: "start" | "stop" | "restart") => {
      try {
        if (verb === "start") {
          await api.startGateway();
          setActiveAction("gateway-start");
        } else if (verb === "stop") {
          await api.stopGateway();
          setActiveAction("gateway-stop");
        } else {
          await api.restartGateway();
          setActiveAction("gateway-restart");
        }
        showToast(`Gateway ${verb} started`, "success");
        setTimeout(loadAll, 3000);
      } catch (e) {
        showToast(`Gateway ${verb} failed: ${e}`, "error");
      }
    },
    [loadAll, showToast],
  );

  // ── Curator (Y3, frozen actions) ───────────────────────────────────
  const toggleCuratorPaused = useCallback(async () => {
    if (!curator) return;
    try {
      await api.setCuratorPaused(!curator.paused);
      showToast(
        curator.paused ? "Curator resumed" : "Curator paused",
        "success",
      );
      loadAll();
    } catch (e) {
      showToast(`Curator toggle failed: ${e}`, "error");
    }
  }, [curator, loadAll, showToast]);

  // ── Operations (Y6): spawn → shared action log (CN10) ──────────────
  const runOp = useCallback(
    async (fn: () => Promise<{ name: string }>, label: string) => {
      try {
        const res = await fn();
        setActiveAction(res.name);
        showToast(`${label} started`, "success");
      } catch (e) {
        showToast(`${label} failed: ${e}`, "error");
      }
    },
    [showToast],
  );

  const handleActionComplete = useCallback(
    (action: string, exitCode: number | null) => {
      completionSeq.current += 1;
      setLastCompletion({ action, exitCode, seq: completionSeq.current });
    },
    [],
  );

  const canUpdateHermes = status?.can_update_hermes !== false;

  return (
    <div className="flex flex-col gap-8">
      <Toast toast={toast} />

      {/* Live action log — pinned above all sections while an action runs (Y1). */}
      {activeAction && (
        <ActionLogViewer
          action={activeAction}
          onComplete={handleActionComplete}
          onClose={() => setActiveAction(null)}
        />
      )}

      {/* ── Host / system stats (Y11) ─────────────────────────────── */}
      <SystemSection
        icon={Server}
        title={ts?.host ?? "Host"}
        loading={!settled.stats}
      >
        <HostCard
          stats={stats}
          canUpdateHermes={canUpdateHermes}
          updateInfo={updateInfo}
          setUpdateInfo={setUpdateInfo}
          setActiveAction={setActiveAction}
          showToast={showToast}
        />
      </SystemSection>

      {/* ── Gateway (Y2 — slot 2: "is my agent process up") ───────── */}
      <SystemSection
        icon={Power}
        title={ts?.gateway ?? "Gateway"}
        loading={!settled.status}
      >
        <GatewayCard status={status} onVerb={(verb) => void runGateway(verb)} />
      </SystemSection>

      {/* ── Network / AI egress contract (Y12 — frozen card, N26) ── */}
      {!settled.status ? (
        <div aria-busy="true">
          <Skeleton variant="block" />
        </div>
      ) : status?.egress ? (
        <EgressStatusCard egress={status.egress} />
      ) : null}

      {/* ── Portal (Y13) — a failed fetch hides only this card (Y14) ─ */}
      {(!settled.portal || portal) && (
        <SystemSection
          icon={Globe}
          title={ts?.portal ?? "Nous Portal"}
          loading={!settled.portal}
        >
          {portal && <PortalCard portal={portal} />}
        </SystemSection>
      )}

      {/* ── Curator (Y3) ──────────────────────────────────────────── */}
      <SystemSection
        icon={Sparkles}
        title={ts?.curator ?? "Skill curator"}
        loading={!settled.curator}
      >
        <CuratorCard
          curator={curator}
          onTogglePaused={() => void toggleCuratorPaused()}
          onRunNow={() => void runOp(api.runCurator, "Curator review")}
        />
      </SystemSection>

      {/* ── Memory (Y4) ───────────────────────────────────────────── */}
      <SystemSection
        icon={Brain}
        title={ts?.memory ?? "Memory"}
        loading={!settled.memory}
      >
        <MemoryCard memory={memory} showToast={showToast} reload={loadAll} />
      </SystemSection>

      {/* ── Credential pool (Y5) ──────────────────────────────────── */}
      <SystemSection
        icon={KeyRound}
        title={ts?.credentialPool ?? "Credential pool"}
        loading={!settled.pool}
      >
        <CredentialPoolCard
          pool={pool}
          showToast={showToast}
          reload={loadAll}
        />
      </SystemSection>

      {/* ── Operations (Y6/Y7/Y8) ─────────────────────────────────── */}
      <SystemSection icon={Activity} title={ts?.operations ?? "Operations"}>
        <OperationsCard onRunOp={(fn, label) => void runOp(fn, label)} />
        <BackupRestoreCard
          setActiveAction={setActiveAction}
          showToast={showToast}
          lastCompletion={lastCompletion}
        />
        <DebugShareCard showToast={showToast} />
      </SystemSection>

      {/* ── Checkpoints ───────────────────────────────────────────── */}
      <SystemSection
        icon={Database}
        title={ts?.checkpoints ?? "Checkpoints"}
        loading={!settled.checkpoints}
      >
        <CheckpointsCard
          checkpoints={checkpoints}
          setActiveAction={setActiveAction}
          showToast={showToast}
        />
      </SystemSection>

      {/* ── Shell hooks (Y10) ─────────────────────────────────────── */}
      <ShellHooksSection
        hooks={hooks}
        loading={!settled.hooks}
        showToast={showToast}
        reload={loadAll}
      />
    </div>
  );
}
