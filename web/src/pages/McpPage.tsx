import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { Package, Server, X } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { api } from "@/lib/api";
import type {
  McpCatalogDiagnostic,
  McpCatalogEntry,
  McpServer,
  McpServerCreate,
  McpTestResult,
} from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn, themedBody } from "@/lib/utils";
import { EmptyState, Skeleton } from "@/components/ui";
import {
  McpServerRow,
  type McpProbeKind,
  type McpProbeRecord,
} from "@/components/mcp/McpServerRow";
import { McpCatalogRow } from "@/components/mcp/McpCatalogRow";
import { McpInstallLogCard } from "@/components/mcp/McpInstallLogCard";
import { useI18n } from "@/i18n";

type Transport = "http" | "stdio";

function truncateText(value: string, maxLength: number): string {
  return value.length > maxLength ? value.slice(0, maxLength) + "..." : value;
}

function parseArgs(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function parseEnv(raw: string): Record<string, string> {
  const env: Record<string, string> = {};
  raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const idx = line.indexOf("=");
      if (idx === -1) return;
      const key = line.slice(0, idx).trim();
      const value = line.slice(idx + 1).trim();
      if (key) env[key] = value;
    });
  return env;
}

/** Section-scoped destructive banner + Retry (X11) — a broken catalog
 *  must never hide configured servers, so each section owns its error. */
function SectionErrorBanner({
  message,
  retryLabel,
  onRetry,
}: {
  message: string;
  retryLabel: string;
  onRetry(): void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border border-destructive/40 bg-destructive/10 px-3 py-2">
      <p className="text-xs text-destructive">{message}</p>
      <Button outlined size="xs" onClick={onRetry}>
        {retryLabel}
      </Button>
    </div>
  );
}

export default function McpPage() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [catalog, setCatalog] = useState<McpCatalogEntry[]>([]);
  const [diagnostics, setDiagnostics] = useState<McpCatalogDiagnostic[]>([]);
  const [loading, setLoading] = useState(true);
  const [serversError, setServersError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();
  const { t } = useI18n();
  const M = t.mcp;

  // Add server modal state
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [transport, setTransport] = useState<Transport>("http");
  const [url, setUrl] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [env, setEnv] = useState("");
  const [creating, setCreating] = useState(false);
  const closeCreateModal = useCallback(() => setCreateModalOpen(false), []);
  const createModalRef = useModalBehavior({
    open: createModalOpen,
    onClose: closeCreateModal,
  });

  // Probe (test/auth) results keyed by server name — probe-time outcomes
  // with timestamps, session-local by design: there is no persisted MCP
  // health to render a standing badge from (X-decision 1).
  const [probes, setProbes] = useState<Record<string, McpProbeRecord>>({});
  // Single busy key across `/test` and `/auth` — both block server-side
  // for seconds-to-minutes, so one probe at a time, row-local UI (X6/R17).
  const [probing, setProbing] = useState<{
    name: string;
    kind: McpProbeKind;
  } | null>(null);

  // Enable/disable state
  const [togglingName, setTogglingName] = useState<string | null>(null);
  const [restartNote, setRestartNote] = useState<string | null>(null);

  // Catalog install modal state
  const [installEntry, setInstallEntry] = useState<McpCatalogEntry | null>(
    null,
  );
  const [installEnv, setInstallEnv] = useState<Record<string, string>>({});
  const [installingName, setInstallingName] = useState<string | null>(null);
  // Background git-bootstrap install being tailed (X8, CAP10 log card).
  const [installAction, setInstallAction] = useState<string | null>(null);
  const closeInstallModal = useCallback(() => setInstallEntry(null), []);
  const installModalRef = useModalBehavior({
    open: installEntry !== null,
    onClose: closeInstallModal,
  });

  const loadServers = useCallback(() => {
    return api
      .getMcpServers()
      .then((res) => {
        setServers(res.servers);
        setServersError(null);
      })
      .catch((e) => setServersError(String(e)));
  }, []);

  const loadCatalog = useCallback(() => {
    return api
      .getMcpCatalog()
      .then((res) => {
        setCatalog(res.entries);
        setDiagnostics(res.diagnostics);
        setCatalogError(null);
      })
      .catch((e) => setCatalogError(String(e)));
  }, []);

  useEffect(() => {
    Promise.all([loadServers(), loadCatalog()]).finally(() =>
      setLoading(false),
    );
  }, [loadServers, loadCatalog]);

  const handleCreate = async () => {
    if (!name.trim()) {
      showToast("Name required", "error");
      return;
    }
    if (transport === "http" && !url.trim()) {
      showToast("URL required", "error");
      return;
    }
    if (transport === "stdio" && !command.trim()) {
      showToast("Command required", "error");
      return;
    }
    setCreating(true);
    try {
      const body: McpServerCreate = { name: name.trim() };
      if (transport === "http") {
        body.url = url.trim();
      } else {
        body.command = command.trim();
        const argList = parseArgs(args);
        if (argList.length) body.args = argList;
      }
      const envMap = parseEnv(env);
      if (Object.keys(envMap).length) body.env = envMap;

      await api.addMcpServer(body);
      showToast("Add ✓", "success");
      setName("");
      setUrl("");
      setCommand("");
      setArgs("");
      setEnv("");
      setTransport("http");
      setCreateModalOpen(false);
      loadServers();
    } catch (e) {
      showToast(`Failed to add: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  /** Shared `/test` + `/auth` runner — same busy key, same result shape:
   *  both record a timestamped probe outcome on the row (X2/X6). */
  const runProbe = useCallback(
    async (server: McpServer, kind: McpProbeKind) => {
      setProbing({ name: server.name, kind });
      try {
        const result: McpTestResult =
          kind === "auth"
            ? await api.authMcpServer(server.name)
            : await api.testMcpServer(server.name);
        setProbes((prev) => ({
          ...prev,
          [server.name]: { result, at: Date.now() },
        }));
        if (result.ok) {
          showToast(
            `${server.name}: ${result.tools.length} tool(s)`,
            "success",
          );
        } else {
          showToast(`${server.name}: ${result.error ?? "Failed"}`, "error");
        }
      } catch (e) {
        showToast(`Error: ${e}`, "error");
      } finally {
        setProbing(null);
      }
    },
    [showToast],
  );

  const handleToggleEnabled = async (server: McpServer) => {
    const next = !server.enabled;
    setTogglingName(server.name);
    try {
      await api.setMcpServerEnabled(server.name, next);
      setServers((prev) =>
        prev.map((s) =>
          s.name === server.name ? { ...s, enabled: next } : s,
        ),
      );
      setRestartNote(
        M?.restartNote ??
          "Enable/disable takes effect on the next gateway restart.",
      );
    } catch (e) {
      showToast(`Error: ${e}`, "error");
    } finally {
      setTogglingName(null);
    }
  };

  const serverDelete = useConfirmDelete({
    onDelete: useCallback(
      async (serverName: string) => {
        try {
          await api.removeMcpServer(serverName);
          showToast(`Delete: "${truncateText(serverName, 30)}"`, "success");
          setProbes((prev) => {
            const next = { ...prev };
            delete next[serverName];
            return next;
          });
          loadServers();
        } catch (e) {
          showToast(`Error: ${e}`, "error");
          throw e;
        }
      },
      [loadServers, showToast],
    ),
  });

  // ── Catalog install ──────────────────────────────────────────────────
  const runInstall = useCallback(
    async (entry: McpCatalogEntry, envMap: Record<string, string>) => {
      setInstallingName(entry.name);
      try {
        const res = await api.installMcpCatalogEntry(entry.name, envMap, true);
        setInstallEntry(null);
        setInstallEnv({});
        if (res.background && res.action) {
          // Git-bootstrap install: tail the spawned action's log (X8);
          // lists reload when it finishes — an immediate reload would
          // show nothing changed for slow clones.
          showToast(
            M?.installingBackground ?? "Installing in background…",
            "success",
          );
          setInstallAction(res.action);
        } else {
          showToast(`Installed: "${truncateText(entry.name, 30)}"`, "success");
          await Promise.all([loadServers(), loadCatalog()]);
        }
      } catch (e) {
        showToast(`Failed to install: ${e}`, "error");
      } finally {
        setInstallingName(null);
      }
    },
    [loadServers, loadCatalog, showToast, M],
  );

  const handleInstallClick = (entry: McpCatalogEntry) => {
    if (entry.required_env.length > 0) {
      const initial: Record<string, string> = {};
      entry.required_env.forEach((item) => {
        initial[item.name] = "";
      });
      setInstallEnv(initial);
      setInstallEntry(entry);
    } else {
      void runInstall(entry, {});
    }
  };

  const handleInstallSubmit = () => {
    if (!installEntry) return;
    const missing = installEntry.required_env.filter(
      (item) => item.required && !(installEnv[item.name] ?? "").trim(),
    );
    if (missing.length > 0) {
      showToast(`${missing[0].prompt} required`, "error");
      return;
    }
    const envMap: Record<string, string> = {};
    Object.entries(installEnv).forEach(([k, v]) => {
      if (v.trim()) envMap[k] = v.trim();
    });
    void runInstall(installEntry, envMap);
  };

  const handleInstallFinished = useCallback(() => {
    void Promise.all([loadServers(), loadCatalog()]);
  }, [loadServers, loadCatalog]);

  // Put "Add Server" button in page header
  useLayoutEffect(() => {
    setEnd(
      <Button
        className="uppercase"
        size="sm"
        onClick={() => setCreateModalOpen(true)}
      >
        {M?.addServer ?? "Add Server"}
      </Button>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, loading, M]);

  if (loading) {
    // Layout-shaped skeletons instead of a page-blocking spinner (X9).
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        <Skeleton variant="row-list" rows={3} />
        <Skeleton variant="row-list" rows={5} />
      </div>
    );
  }

  const diagnosticsByName: Record<string, McpCatalogDiagnostic[]> = {};
  diagnostics.forEach((d) => {
    (diagnosticsByName[d.name] ??= []).push(d);
  });

  const enabledCount = servers.filter((s) => s.enabled).length;

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={serverDelete.isOpen}
        onCancel={serverDelete.cancel}
        onConfirm={serverDelete.confirm}
        title="Remove MCP server"
        description={
          serverDelete.pendingId
            ? `"${truncateText(serverDelete.pendingId, 40)}" — this will remove the server.`
            : "This will remove the server."
        }
        loading={serverDelete.isDeleting}
      />

      {/* Add server modal */}
      {createModalOpen && (
        <div
          ref={createModalRef}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
          onClick={(e) =>
            e.target === e.currentTarget && setCreateModalOpen(false)
          }
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-mcp-title"
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
              onClick={() => setCreateModalOpen(false)}
              className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X />
            </Button>

            <header className="p-5 pb-3 border-b border-border">
              <h2
                id="create-mcp-title"
                className="font-mondwest text-display text-base tracking-wider"
              >
                Add MCP server
              </h2>
            </header>

            <div className="p-5 grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="mcp-name">Name</Label>
                <Input
                  id="mcp-name"
                  autoFocus
                  placeholder="my-server"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="mcp-transport">Transport</Label>
                <Select
                  id="mcp-transport"
                  value={transport}
                  onValueChange={(v) => setTransport(v as Transport)}
                >
                  <SelectOption value="http">HTTP/SSE</SelectOption>
                  <SelectOption value="stdio">stdio</SelectOption>
                </Select>
              </div>

              {transport === "http" ? (
                <div className="grid gap-2">
                  <Label htmlFor="mcp-url">URL</Label>
                  <Input
                    id="mcp-url"
                    placeholder="https://example.com/mcp"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                  />
                </div>
              ) : (
                <>
                  <div className="grid gap-2">
                    <Label htmlFor="mcp-command">Command</Label>
                    <Input
                      id="mcp-command"
                      placeholder="npx"
                      value={command}
                      onChange={(e) => setCommand(e.target.value)}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="mcp-args">Args</Label>
                    <Input
                      id="mcp-args"
                      placeholder="-y @modelcontextprotocol/server-foo"
                      value={args}
                      onChange={(e) => setArgs(e.target.value)}
                    />
                  </div>
                </>
              )}

              <div className="grid gap-2">
                <Label htmlFor="mcp-env">Environment (KEY=VALUE per line)</Label>
                <textarea
                  id="mcp-env"
                  className="flex min-h-[80px] w-full border border-border bg-background/40 px-3 py-2 text-sm font-courier shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30 focus-visible:border-foreground/25"
                  placeholder={"API_KEY=secret\nDEBUG=1"}
                  value={env}
                  onChange={(e) => setEnv(e.target.value)}
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
                  {creating ? "Adding..." : "Add"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Catalog install modal (required env vars) */}
      {installEntry && (
        <div
          ref={installModalRef}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
          onClick={(e) =>
            e.target === e.currentTarget && setInstallEntry(null)
          }
          role="dialog"
          aria-modal="true"
          aria-labelledby="install-mcp-title"
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
              onClick={() => setInstallEntry(null)}
              className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X />
            </Button>

            <header className="p-5 pb-3 border-b border-border">
              <h2
                id="install-mcp-title"
                className="font-mondwest text-display text-base tracking-wider"
              >
                Install {installEntry.name}
              </h2>
            </header>

            <div className="p-5 grid gap-4">
              <p className="text-xs text-muted-foreground">
                This MCP requires the following values to be configured.
              </p>
              {installEntry.required_env.map((item) => (
                <div className="grid gap-2" key={item.name}>
                  <Label htmlFor={`install-env-${item.name}`}>
                    {item.prompt}
                    {item.required ? " *" : ""}
                  </Label>
                  <Input
                    id={`install-env-${item.name}`}
                    type="password"
                    placeholder={item.name}
                    value={installEnv[item.name] ?? ""}
                    onChange={(e) =>
                      setInstallEnv((prev) => ({
                        ...prev,
                        [item.name]: e.target.value,
                      }))
                    }
                  />
                </div>
              ))}

              <div className="flex justify-end">
                <Button
                  className="uppercase"
                  size="sm"
                  onClick={handleInstallSubmit}
                  disabled={installingName === installEntry.name}
                  prefix={
                    installingName === installEntry.name ? (
                      <Spinner />
                    ) : undefined
                  }
                >
                  {installingName === installEntry.name
                    ? (M?.installing ?? "Installing...")
                    : (M?.install ?? "Install")}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Your MCP servers (X1: roster first) ── */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <H2
            variant="sm"
            className="flex items-center gap-2 text-muted-foreground"
          >
            <Server className="h-4 w-4" />
            {M?.yourServers ?? "Your MCP servers"} ({servers.length})
          </H2>
          {servers.length > 0 && (
            // Honest client-side summary — config counts, no fake health
            // tally (X3 / X-decision 1).
            <p className="font-mono-ui text-xs tabular-nums text-muted-foreground">
              {(M?.serversSummary ?? "{n} servers · {m} enabled")
                .replace("{n}", String(servers.length))
                .replace("{m}", String(enabledCount))}
            </p>
          )}
        </div>

        {serversError && (
          <SectionErrorBanner
            message={M?.loadServersFailed ?? "Failed to load MCP servers"}
            retryLabel={t.common.retry}
            onRetry={() => void loadServers()}
          />
        )}

        {!serversError && servers.length === 0 && (
          <EmptyState
            icon={Server}
            title={M?.noServersTitle ?? "No MCP servers"}
            description={
              M?.noServersDescription ??
              "Add a server or install one from the catalog below."
            }
            action={
              <Button
                className="uppercase"
                size="sm"
                onClick={() => setCreateModalOpen(true)}
              >
                {M?.addServer ?? "Add Server"}
              </Button>
            }
          />
        )}

        {servers.map((server) => (
          <McpServerRow
            key={server.name}
            server={server}
            probe={probes[server.name]}
            busy={probing?.name === server.name ? probing.kind : null}
            probeLocked={probing !== null}
            toggling={togglingName === server.name}
            onToggleEnabled={() => void handleToggleEnabled(server)}
            onTest={() => void runProbe(server, "test")}
            onLogin={() => void runProbe(server, "auth")}
            onDelete={() => serverDelete.requestDelete(server.name)}
          />
        ))}
      </div>

      {restartNote && (
        // R16 truthfulness strip (X1 item 2, between roster and catalog):
        // enabled ≠ running until the gateway restarts — warning-tinted
        // 1px box (X2).
        <div className="border border-warning/40 bg-warning/10 px-3 py-2">
          <p className="text-xs text-warning">{restartNote}</p>
        </div>
      )}

      {/* ── Catalog ── */}
      <div className="flex flex-col gap-3">
        <H2
          variant="sm"
          className="flex items-center gap-2 text-muted-foreground"
        >
          <Package className="h-4 w-4" />
          {M?.catalog ?? "Catalog"} ({catalog.length})
        </H2>

        <p className="text-xs text-muted-foreground">
          {M?.catalogIntro ??
            "Browse Fabric-curated MCP servers and install them with one click."}
        </p>

        {/* Background-install log tail (X8, CAP10) — at the top of the
            catalog section while a git-bootstrap install runs. */}
        {installAction && (
          <McpInstallLogCard
            key={installAction}
            action={installAction}
            onFinished={handleInstallFinished}
            onDismiss={() => setInstallAction(null)}
          />
        )}

        {catalogError && (
          <SectionErrorBanner
            message={M?.loadCatalogFailed ?? "Failed to load the catalog"}
            retryLabel={t.common.retry}
            onRetry={() => void loadCatalog()}
          />
        )}

        {!catalogError && catalog.length === 0 && (
          <EmptyState
            icon={Package}
            title={M?.noCatalogTitle ?? "No catalog entries available"}
          />
        )}

        {catalog.map((entry) => (
          <McpCatalogRow
            key={entry.name}
            entry={entry}
            diagnostics={diagnosticsByName[entry.name] ?? []}
            installing={installingName === entry.name}
            onInstall={() => handleInstallClick(entry)}
          />
        ))}
      </div>
    </div>
  );
}
