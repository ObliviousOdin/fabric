import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Bot,
  CalendarClock,
  CircleAlert,
  Gauge,
  MessageSquare,
  Network,
  ShieldCheck,
} from "lucide-react";
import { Skeleton } from "@/components/ui";
import { ScreenState } from "@/components/experience/ScreenState";
import {
  StatusSignal,
  type FabricStatusTone,
} from "@/components/fabric/StatusSignal";
import { useProfileScope } from "@/contexts/useProfileScope";
import { api } from "@/lib/api";
import type { CronSummary, SessionInfo, StatusResponse } from "@/lib/api";
import { freshChatPath } from "@/components/chat/usePersistentChatIdentity";

interface HomeProjection {
  status: StatusResponse | null;
  sessions: SessionInfo[];
  automations: CronSummary | null;
}

interface ProjectionErrors {
  status: boolean;
  sessions: boolean;
  automations: boolean;
}

type ProjectionLoading = ProjectionErrors;

const EMPTY_PROJECTION: HomeProjection = {
  status: null,
  sessions: [],
  automations: null,
};

const NO_ERRORS: ProjectionErrors = {
  status: false,
  sessions: false,
  automations: false,
};

const ALL_LOADING: ProjectionLoading = {
  status: true,
  sessions: true,
  automations: true,
};

function relativeTime(epochSeconds: number): string {
  const deltaSeconds = Math.round(epochSeconds - Date.now() / 1000);
  const absolute = Math.abs(deltaSeconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (absolute < 60) return formatter.format(deltaSeconds, "second");
  if (absolute < 3600)
    return formatter.format(Math.round(deltaSeconds / 60), "minute");
  if (absolute < 86_400)
    return formatter.format(Math.round(deltaSeconds / 3600), "hour");
  return formatter.format(Math.round(deltaSeconds / 86_400), "day");
}

function PanelLink({
  to,
  children,
  primary = false,
}: {
  to: string;
  children: string;
  primary?: boolean;
}) {
  return (
    <Link
      to={to}
      className={
        primary
          ? "inline-flex min-h-11 items-center gap-2 bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          : "inline-flex min-h-11 items-center gap-2 px-2 text-sm font-medium text-foreground underline decoration-border decoration-1 underline-offset-4 transition-colors hover:text-primary hover:decoration-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      }
    >
      {children}
      <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
    </Link>
  );
}

function FreshChatLink({
  children,
  primary = false,
}: {
  children: string;
  primary?: boolean;
}) {
  const [to] = useState(freshChatPath);
  return (
    <PanelLink primary={primary} to={to}>
      {children}
    </PanelLink>
  );
}

function PulseMetric({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="min-w-0 px-4 py-4 sm:px-5">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-foreground">
        {value}
      </div>
      <p className="mt-1 truncate text-xs text-muted-foreground" title={detail}>
        {detail}
      </p>
    </div>
  );
}

function AttentionRow({
  description,
  icon: Icon,
  label,
  signal,
  tone = "neutral",
}: {
  description: string;
  icon: typeof Gauge;
  label: string;
  signal: string;
  tone?: FabricStatusTone;
}) {
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 border-b border-border/70 py-4 last:border-b-0">
      <Icon aria-hidden="true" className="mt-0.5 h-4 w-4 text-text-tertiary" />
      <div className="min-w-0">
        <StatusSignal label={label} tone={tone} />
        <p className="mt-1 text-sm leading-relaxed text-text-secondary">
          {description}
        </p>
        <p className="mt-2 text-xs font-medium text-text-tertiary">{signal}</p>
      </div>
    </li>
  );
}

/**
 * Workspace landing page built entirely from existing, truthful projections.
 * Durable work and approval counts are intentionally absent until their
 * scoped backend contracts exist.
 */
export default function WorkspaceHomePage() {
  const { profile, currentProfile } = useProfileScope();
  const [projection, setProjection] =
    useState<HomeProjection>(EMPTY_PROJECTION);
  const [errors, setErrors] = useState<ProjectionErrors>(NO_ERRORS);
  const [loading, setLoading] = useState<ProjectionLoading>(ALL_LOADING);
  const [reloadKey, setReloadKey] = useState(0);
  const selectedProfile = profile || currentProfile || "default";

  useEffect(() => {
    let active = true;

    const settle = (key: keyof ProjectionLoading, failed: boolean) => {
      if (!active) return;
      setErrors((current) => ({ ...current, [key]: failed }));
      setLoading((current) => ({ ...current, [key]: false }));
    };

    void api
      .getStatus()
      .then((status) => {
        if (active) setProjection((current) => ({ ...current, status }));
        settle("status", false);
      })
      .catch(() => settle("status", true));

    void api
      .getSessions(6, 0, undefined, "recent")
      .then((result) => {
        if (active) {
          setProjection((current) => ({
            ...current,
            sessions: result.sessions,
          }));
        }
        settle("sessions", false);
      })
      .catch(() => settle("sessions", true));

    // Home is scoped to the selected agent profile. Avoid the default
    // all-profile materialization when only aggregate cards are displayed.
    void api
      .getCronSummary(selectedProfile)
      .then((automations) => {
        if (active) {
          setProjection((current) => ({ ...current, automations }));
        }
        settle("automations", false);
      })
      .catch(() => settle("automations", true));

    return () => {
      active = false;
    };
  }, [reloadKey, selectedProfile]);

  const activeSessions = useMemo(
    () => projection.sessions.filter((session) => session.is_active).length,
    [projection.sessions],
  );
  const enabledAutomations = projection.automations?.enabled ?? 0;
  const failedAutomations = projection.automations?.failed ?? 0;
  const hasAnyError = errors.status || errors.sessions || errors.automations;
  const reload = () => {
    setLoading(ALL_LOADING);
    setErrors(NO_ERRORS);
    setReloadKey((key) => key + 1);
  };

  return (
    <div className="fabric-woven-canvas min-h-full px-4 pb-8 pt-5 sm:px-6 lg:px-8 lg:pt-7">
      <div className="mx-auto w-full max-w-[96rem]">
        <header className="grid gap-6 border-b border-border/80 pb-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium text-text-tertiary">
              <span className="inline-flex items-center gap-2 text-primary">
                <span aria-hidden className="h-px w-7 bg-primary" />
                Workspace
              </span>
              <span aria-hidden>/</span>
              <span>Agent profile: {selectedProfile}</span>
              <span aria-hidden>/</span>
              <span>
                {loading.status
                  ? "Checking access"
                  : errors.status
                    ? "Access unknown"
                    : projection.status?.auth_required
                      ? "Authentication required"
                      : "Local access"}
              </span>
            </div>
            <h1 className="mt-4 text-4xl font-semibold tracking-[-0.035em] text-foreground sm:text-5xl">
              Now
            </h1>
            <p className="mt-3 max-w-2xl text-base leading-relaxed text-text-secondary">
              Follow the conversations moving through Fabric and the operational
              signals that need attention.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <FreshChatLink primary>
              Start a conversation
            </FreshChatLink>
            <PanelLink to="/workspace/work">Open Work Board</PanelLink>
          </div>
        </header>

        {hasAnyError && (
          <div className="flex flex-col gap-4 border-b border-border/80 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <StatusSignal
                label="Some live signals are unavailable"
                tone="warning"
              />
              <p className="mt-1 pl-5 text-sm text-text-secondary">
                Available sections remain usable while status, conversations,
                and automations refresh independently.
              </p>
            </div>
            <button
              type="button"
              className="min-h-11 shrink-0 border border-border bg-background-base px-4 text-sm font-medium text-foreground transition-colors hover:border-primary hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={reload}
            >
              Retry signals
            </button>
          </div>
        )}

        <div className="grid border-b border-border/80 lg:grid-cols-[minmax(0,1.45fr)_minmax(22rem,0.75fr)]">
          <section
            className="min-w-0 py-6 lg:border-r lg:border-border/80 lg:pr-8"
            aria-labelledby="active-threads-heading"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2
                  id="active-threads-heading"
                  className="text-xl font-semibold text-foreground"
                >
                  Active threads
                </h2>
                <p className="mt-1 text-sm text-text-secondary">
                  Recent conversation activity for the selected agent profile.
                </p>
              </div>
              <PanelLink to="/workspace/conversations">
                All conversations
              </PanelLink>
            </div>

            <div className="mt-5">
              {loading.sessions && projection.sessions.length === 0 ? (
                <div aria-label="Loading recent conversations" role="status">
                  <Skeleton variant="block" className="h-56" />
                </div>
              ) : errors.sessions ? (
                <ScreenState
                  compact
                  kind="failure"
                  title="Conversations could not be loaded"
                  description="The Chat terminal remains independent and may still be available."
                />
              ) : projection.sessions.length === 0 ? (
                <ScreenState
                  compact
                  kind="empty"
                  title="No conversations yet"
                  description="Start in Chat. Fabric will keep the resulting session in the conversation ledger."
                  primaryAction={
                    <FreshChatLink>
                      Start a conversation
                    </FreshChatLink>
                  }
                />
              ) : (
                <ul className="border-t border-border/70">
                  {projection.sessions.map((session) => (
                    <li key={session.id} className="border-b border-border/70">
                      <Link
                        to={`/workspace/chat?resume=${encodeURIComponent(session.id)}`}
                        className="group grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 py-4 pr-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                      >
                        <span className="relative grid h-9 w-9 shrink-0 place-items-center text-text-tertiary group-hover:text-primary">
                          <span
                            aria-hidden
                            className="absolute bottom-0 left-0 top-0 w-0.5 bg-border group-hover:bg-primary"
                          />
                          <span
                            aria-hidden
                            className="absolute bottom-0 left-0 h-0.5 w-3 bg-border group-hover:bg-primary"
                          />
                          <Bot aria-hidden="true" className="h-4 w-4" />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-foreground">
                            {session.title ||
                              session.preview ||
                              "Untitled conversation"}
                          </span>
                          <span className="mt-1 block truncate text-xs text-text-tertiary">
                            {session.source || "unknown source"} ·{" "}
                            {relativeTime(session.last_active)}
                          </span>
                        </span>
                        <StatusSignal
                          compact={false}
                          label={session.is_active ? "Active" : "Idle"}
                          pulse={session.is_active}
                          tone={session.is_active ? "live" : "neutral"}
                        />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section
            className="min-w-0 py-6 lg:pl-8"
            aria-labelledby="attention-heading"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2
                  id="attention-heading"
                  className="text-xl font-semibold text-foreground"
                >
                  Attention
                </h2>
                <p className="mt-1 text-sm text-text-secondary">
                  Runtime boundaries and signals, without synthetic work counts.
                </p>
              </div>
              <PanelLink to="/admin/system">System</PanelLink>
            </div>

            <ul className="mt-5 border-t border-border/70">
              <AttentionRow
                description={
                  loading.status
                    ? "Loading runtime process state."
                    : projection.status?.gateway_exit_reason ||
                      "The local agent gateway reports its current process state."
                }
                icon={Gauge}
                label={
                  loading.status
                    ? "Checking gateway"
                    : errors.status
                      ? "Gateway unavailable"
                      : projection.status?.gateway_running
                        ? "Gateway live"
                        : "Gateway idle"
                }
                signal={projection.status?.gateway_state ?? "No state reported"}
                tone={
                  loading.status
                    ? "neutral"
                    : errors.status
                      ? "warning"
                      : projection.status?.gateway_running
                        ? "success"
                        : "neutral"
                }
              />
              <AttentionRow
                description={
                  loading.automations
                    ? "Loading automation outcomes."
                    : errors.automations
                      ? "Automation status is unavailable."
                      : failedAutomations
                        ? `${failedAutomations} automation failure${failedAutomations === 1 ? "" : "s"} may need intervention.`
                        : "No automation failures are currently reported."
                }
                icon={CircleAlert}
                label={
                  loading.automations
                    ? "Checking automations"
                    : errors.automations
                      ? "Automation signal unavailable"
                      : failedAutomations
                        ? "Automation intervention"
                        : "Automations clear"
                }
                signal={`${enabledAutomations} enabled for ${selectedProfile}`}
                tone={
                  errors.automations || failedAutomations
                    ? "warning"
                    : "success"
                }
              />
              <AttentionRow
                description={
                  loading.status
                    ? "Loading dashboard access mode."
                    : projection.status?.auth_required
                      ? "Dashboard authentication is required."
                      : "Loopback runtime access is limited to this local dashboard."
                }
                icon={ShieldCheck}
                label="Access context"
                signal={projection.status?.auth_required ? "Gated" : "Loopback"}
                tone={projection.status?.auth_required ? "success" : "neutral"}
              />
            </ul>

            <div className="mt-5 border-l-2 border-primary/45 pl-4">
              <p className="text-sm font-medium text-foreground">
                Durable work and approvals remain explicit
              </p>
              <p className="mt-1 text-sm leading-relaxed text-text-secondary">
                Their scoped projections appear here only after the backend
                contracts exist.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <PanelLink to="/workspace/work">Work Board</PanelLink>
                <PanelLink to="/workspace/approvals">Approvals</PanelLink>
              </div>
            </div>
          </section>
        </div>

        <section
          aria-label="Operational pulse"
          className="grid divide-y divide-border/70 border-b border-border/80 sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-4"
        >
          <PulseMetric
            icon={Network}
            label="Gateway"
            value={
              loading.status
                ? "…"
                : errors.status
                  ? "Unknown"
                  : projection.status?.gateway_running
                    ? "Live"
                    : "Idle"
            }
            detail={
              loading.status
                ? "Loading runtime state"
                : (projection.status?.gateway_state ?? "No live state reported")
            }
          />
          <PulseMetric
            icon={MessageSquare}
            label="Active conversations"
            value={
              loading.status && loading.sessions
                ? "…"
                : String(projection.status?.active_sessions ?? activeSessions)
            }
            detail={
              loading.status && loading.sessions
                ? "Loading conversation activity"
                : `${projection.sessions.length} recent conversations loaded`
            }
          />
          <PulseMetric
            icon={CalendarClock}
            label="Enabled automations"
            value={
              loading.automations
                ? "…"
                : errors.automations
                  ? "Unknown"
                  : String(enabledAutomations)
            }
            detail={
              loading.automations
                ? "Loading automation status"
                : `${projection.automations?.total ?? 0} configured for this profile`
            }
          />
          <PulseMetric
            icon={Activity}
            label="Automation failures"
            value={
              loading.automations
                ? "…"
                : errors.automations
                  ? "Unknown"
                  : String(failedAutomations)
            }
            detail={
              failedAutomations
                ? "Intervention may be required"
                : "No reported failures"
            }
          />
        </section>
      </div>
    </div>
  );
}
