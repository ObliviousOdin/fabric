import { LogIn, Power, Server, Trash2, Zap } from "lucide-react";
import { Badge } from "@/components/fabric/Badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import type { McpServer, McpTestResult } from "@/lib/api";
import {
  CAPABILITY_STATE_TONES,
  CapabilityRow,
  RelativeTime,
  mcpProbeOutcome,
  mcpServerCapabilityState,
} from "@/components/ui";
import { useI18n } from "@/i18n";

/** Which blocking probe is in flight for this server (single busy key —
 *  `/test` and `/auth` share it so concurrent probes are impossible, X6). */
export type McpProbeKind = "test" | "auth";

/** A probe result plus when it was taken — session-local by design; there
 *  is no persisted MCP health (X-decision 1). */
export interface McpProbeRecord {
  result: McpTestResult;
  /** Epoch ms of the probe (rendered as a RelativeTime on the chip). */
  at: number;
}

export interface McpServerRowProps {
  server: McpServer;
  /** Last `/test` or `/auth` outcome for this server, if probed this session. */
  probe?: McpProbeRecord;
  /** Probe in flight for this server (`null` = idle). */
  busy: McpProbeKind | null;
  /** Any probe in flight anywhere on the page (disables new probes, R17). */
  probeLocked: boolean;
  toggling: boolean;
  onToggleEnabled(): void;
  onTest(): void;
  onLogin(): void;
  onDelete(): void;
}

/** True when a failed probe's error copy suggests an OAuth login would help. */
function errorSuggestsOAuth(result: McpTestResult | undefined): boolean {
  if (!result || result.ok || !result.error) return false;
  return /oauth|401|unauthorized/i.test(result.error);
}

/**
 * MCP server row (CapabilityRow consumer #4, spec X2): mono identity,
 * outline transport/auth provenance badges (transport is provenance, not
 * status — never success/warning-toned), CAP2 `disabled` badge with the
 * takes-effect-on-restart truthfulness in `title` (R16), mono meta line
 * (endpoint/command · env vars · enabled-tool selection), and the last
 * probe outcome as a timestamped chip in the detail zone — never a
 * standing health badge (X-decision 1).
 */
export function McpServerRow({
  server,
  probe,
  busy,
  probeLocked,
  toggling,
  onToggleEnabled,
  onTest,
  onLogin,
  onDelete,
}: McpServerRowProps) {
  const { t } = useI18n();
  const M = t.mcp;

  const state = mcpServerCapabilityState(server);
  const restartCopy =
    M?.restartNote ??
    "Enable/disable takes effect on the next gateway restart.";

  const envCount = Object.keys(server.env ?? {}).length;
  const target =
    server.transport === "http"
      ? (server.url ?? "—")
      : [server.command, ...(server.args ?? [])].filter(Boolean).join(" ") ||
        "—";

  // Login is shown only where it can work: http servers configured for
  // OAuth, or after a probe failure whose error copy points at OAuth (X2).
  const showLogin =
    server.transport === "http" &&
    (server.auth === "oauth" || errorSuggestsOAuth(probe?.result));

  const outcome = probe ? mcpProbeOutcome(probe.result) : null;
  const outcomeLabel = probe
    ? probe.result.ok
      ? `${t.capabilities?.reachable ?? "reachable"} · ${probe.result.tools.length} ${
          probe.result.tools.length === 1 ? "tool" : "tools"
        }`
      : (t.capabilities?.unreachable ?? "unreachable")
    : null;

  const promptCount = probe?.result.prompts ?? 0;
  const resourceCount = probe?.result.resources ?? 0;

  const detail =
    busy === "auth" ? (
      // Persistent inline wait row — the auth request blocks server-side
      // for up to minutes; busy state stays row-local, never page-level
      // (X6/R17).
      <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
        <Spinner />
        <span>{M?.waitingForBrowser ?? "Waiting for the browser OAuth flow…"}</span>
      </div>
    ) : probe && outcome ? (
      <div className="mt-1 flex flex-col gap-1 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          {/* Probe-time outcome chip + its timestamp — a last-outcome
              record, not a health badge (CAP2 / X-decision 1). */}
          <Badge tone={outcome.tone} className="font-mono-ui">
            {outcomeLabel}
          </Badge>
          <RelativeTime
            value={probe.at}
            className="text-muted-foreground"
          />
        </div>
        {probe.result.ok ? (
          <p className="text-muted-foreground break-words">
            {probe.result.tools.length === 0 ? (
              (M?.connectedNoTools ?? "Connected — no tools")
            ) : (
              <span className="font-mono-ui">
                {probe.result.tools.map((tool) => tool.name).join(", ")}
              </span>
            )}
            {promptCount > 0 && (
              <span className="font-mono-ui tabular-nums">
                {" · "}
                {(M?.promptsCount ?? "{n} prompts").replace(
                  "{n}",
                  String(promptCount),
                )}
              </span>
            )}
            {resourceCount > 0 && (
              <span className="font-mono-ui tabular-nums">
                {" · "}
                {(M?.resourcesCount ?? "{n} resources").replace(
                  "{n}",
                  String(resourceCount),
                )}
              </span>
            )}
          </p>
        ) : (
          <p className="text-destructive break-words">
            {probe.result.error ?? "Connection failed"}
          </p>
        )}
      </div>
    ) : null;

  return (
    <CapabilityRow
      name={server.name}
      icon={Server}
      dimmed={!server.enabled}
      badges={
        <>
          {/* Transport is provenance, not status — outline for every
              transport (X2 retone; the old success/warning mapping said
              HTTP is good and stdio is dangerous). */}
          <Badge tone="outline" className="font-mono-ui">
            {server.transport}
          </Badge>
          {state.state === "disabled" && (
            <Badge
              tone={CAPABILITY_STATE_TONES[state.state]}
              title={restartCopy}
            >
              {t.capabilities?.disabled ?? state.label}
            </Badge>
          )}
          {server.auth && (
            <Badge tone="outline" className="font-mono-ui">
              auth: {server.auth}
            </Badge>
          )}
        </>
      }
      meta={
        <>
          <span className="min-w-0 truncate" title={target}>
            {target}
          </span>
          {envCount > 0 && (
            <>
              <span aria-hidden="true">·</span>
              <span>
                {(envCount === 1
                  ? (M?.envVarCount ?? "{n} env var")
                  : (M?.envVarsCount ?? "{n} env vars")
                ).replace("{n}", String(envCount))}
              </span>
            </>
          )}
          {server.tools !== null && (
            <>
              <span aria-hidden="true">·</span>
              {/* Served enabled-tool selection (null = all tools). */}
              <span title={server.tools.join(", ")}>
                {(M?.toolsEnabledCount ?? "{n} tools enabled").replace(
                  "{n}",
                  String(server.tools.length),
                )}
              </span>
            </>
          )}
        </>
      }
      detail={detail}
      actions={
        <>
          <Button
            ghost
            size="sm"
            title={restartCopy}
            aria-label={server.enabled ? "Disable" : "Enable"}
            onClick={onToggleEnabled}
            disabled={toggling}
            prefix={toggling ? <Spinner /> : <Power />}
            className={server.enabled ? "text-success" : undefined}
          >
            {server.enabled ? "Disable" : "Enable"}
          </Button>

          <Button
            ghost
            size="icon"
            title={M?.test ?? "Test connection"}
            aria-label={M?.test ?? "Test connection"}
            onClick={onTest}
            disabled={probeLocked}
          >
            {busy === "test" ? <Spinner /> : <Zap />}
          </Button>

          {showLogin && (
            <Button
              ghost
              size="sm"
              title={M?.login ?? "Login"}
              aria-label={M?.login ?? "Login"}
              onClick={onLogin}
              disabled={probeLocked}
              prefix={busy === "auth" ? <Spinner /> : <LogIn />}
            >
              {M?.login ?? "Login"}
            </Button>
          )}

          <Button
            ghost
            destructive
            size="icon"
            title={t.common.delete}
            aria-label={t.common.delete}
            onClick={onDelete}
          >
            <Trash2 />
          </Button>
        </>
      }
    />
  );
}
