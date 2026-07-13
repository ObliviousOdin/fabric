import { Package } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import type { McpCatalogDiagnostic, McpCatalogEntry } from "@/lib/api";
import { CapabilityRow } from "@/components/ui";
import { useI18n } from "@/i18n";

function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

export interface McpCatalogRowProps {
  entry: McpCatalogEntry;
  diagnostics: McpCatalogDiagnostic[];
  installing: boolean;
  onInstall(): void;
}

/**
 * MCP catalog row (CapabilityRow consumer #5, spec X4): mono identity,
 * outline transport/auth provenance badges (X2 toning — transport is
 * provenance, not status), `installed`/`disabled` state badges, and the
 * full trust-model disclosure in the detail zone — endpoint/command,
 * install source, bootstrap commands and setup notes stay visible
 * pre-install exactly as before (N19).
 */
export function McpCatalogRow({
  entry,
  diagnostics,
  installing,
  onInstall,
}: McpCatalogRowProps) {
  const { t } = useI18n();
  const M = t.mcp;

  const detail = (
    <div className="mt-1 flex flex-col gap-1">
      {/* Connection detail: what the agent actually talks to. */}
      {entry.transport === "http" && entry.url && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium">Endpoint:</span>{" "}
          <code className="font-mono">{entry.url}</code>
        </p>
      )}
      {entry.transport === "stdio" && entry.command && (
        <p className="text-xs text-muted-foreground break-all">
          <span className="font-medium">Runs:</span>{" "}
          <code className="font-mono">
            {[entry.command, ...entry.args].join(" ")}
          </code>
        </p>
      )}
      {/* Git bootstrap — surfaced so users see what gets cloned/run
          before they install (matches the docs trust model, N19). */}
      {entry.install_url && (
        <p className="text-xs text-muted-foreground break-all">
          <span className="font-medium">Installs from:</span>{" "}
          {isHttpUrl(entry.install_url) ? (
            <a
              href={entry.install_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-2 hover:opacity-80"
            >
              {entry.install_url}
            </a>
          ) : (
            <code className="font-mono">{entry.install_url}</code>
          )}
          {entry.install_ref && <span> @ {entry.install_ref}</span>}
        </p>
      )}
      {entry.bootstrap.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none">
            Bootstrap commands ({entry.bootstrap.length})
          </summary>
          <ul className="mt-1 ml-3 list-disc space-y-0.5">
            {entry.bootstrap.map((cmd, i) => (
              <li key={`${entry.name}-bs-${i}`} className="break-all">
                <code className="font-mono">{cmd}</code>
              </li>
            ))}
          </ul>
        </details>
      )}
      {entry.post_install && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none">Setup notes</summary>
          <p className="mt-1 whitespace-pre-wrap">
            {entry.post_install.trim()}
          </p>
        </details>
      )}
      {diagnostics.map((d, i) => (
        <p key={`${entry.name}-diag-${i}`} className="text-xs text-warning">
          {d.message}
        </p>
      ))}
    </div>
  );

  return (
    <CapabilityRow
      name={entry.name}
      icon={Package}
      badges={
        <>
          {/* Transport is provenance, not status — outline, never
              success/warning (X2 retone). */}
          <Badge tone="outline" className="font-mono-ui">
            {entry.transport}
          </Badge>
          <Badge tone="outline" className="font-mono-ui">
            auth: {entry.auth_type}
          </Badge>
          {isHttpUrl(entry.source) ? (
            <a
              href={entry.source}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary underline underline-offset-2 hover:opacity-80"
            >
              source ↗
            </a>
          ) : (
            entry.source && <Badge tone="outline">{entry.source}</Badge>
          )}
          {entry.installed && (
            <Badge tone="success">
              {t.capabilities?.installed ?? "installed"}
            </Badge>
          )}
          {entry.installed && !entry.enabled && (
            <Badge tone="outline">{t.capabilities?.disabled ?? "disabled"}</Badge>
          )}
        </>
      }
      description={entry.description || undefined}
      detail={detail}
      actions={
        // Installed entries already carry the success `installed` state
        // badge in the badges zone — no second badge in the actions zone
        // (CAP1.2: never two badges saying the same thing).
        entry.installed ? undefined : (
          <Button
            className="uppercase"
            size="sm"
            onClick={onInstall}
            disabled={installing}
            prefix={installing ? <Spinner /> : undefined}
          >
            {installing
              ? (M?.installing ?? "Installing...")
              : (M?.install ?? "Install")}
          </Button>
        )
      }
    />
  );
}
