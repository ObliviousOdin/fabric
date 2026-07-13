import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  ExternalLink,
  FileText,
  Globe,
  Loader2,
  Package,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Sparkles,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  SkillHubInstalledEntry,
  SkillHubPreview,
  SkillHubResult,
  SkillHubScan,
  SkillHubSource,
} from "@/lib/api";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@nous-research/ui/ui/components/dialog";
import { Input } from "@nous-research/ui/ui/components/input";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { CapabilityRow, EmptyState, Skeleton } from "@/components/ui";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Hub browser — search the skill hub, preview, scan, install         */
/*  (K8: restyled to shared primitives; behavior frozen — N17.)        */
/* ------------------------------------------------------------------ */

/** Map a trust level to a Badge tone + label. */
function trustVisual(level: string): {
  tone: "success" | "secondary" | "warning" | "outline";
  label: string;
} {
  switch (level) {
    case "trusted":
      return { tone: "success", label: "trusted" };
    case "builtin":
      return { tone: "secondary", label: "builtin" };
    case "community":
      return { tone: "warning", label: "community" };
    default:
      return { tone: "outline", label: level || "unknown" };
  }
}

/** Map a scan verdict to tone + icon. */
function verdictVisual(verdict: string): {
  tone: "success" | "warning" | "destructive";
  Icon: React.ComponentType<{ className?: string }>;
  label: string;
} {
  switch (verdict) {
    case "safe":
      return { tone: "success", Icon: ShieldCheck, label: "Safe" };
    case "caution":
      return { tone: "warning", Icon: ShieldAlert, label: "Caution" };
    case "dangerous":
      return { tone: "destructive", Icon: ShieldAlert, label: "Dangerous" };
    default:
      return { tone: "warning", Icon: ShieldQuestion, label: verdict };
  }
}

const SEVERITY_TONE: Record<
  string,
  "destructive" | "warning" | "secondary" | "outline"
> = {
  critical: "destructive",
  high: "destructive",
  medium: "warning",
  low: "secondary",
};

export interface HubBrowserProps {
  showToast: (msg: string, kind: "success" | "error") => void;
  /** Optional profile scoping installs + installed-state badges. */
  profile?: string;
}

export function HubBrowser({ showToast, profile }: HubBrowserProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SkillHubResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [sourceCounts, setSourceCounts] = useState<Record<string, number>>({});
  const [timedOut, setTimedOut] = useState<string[]>([]);
  const [searchMs, setSearchMs] = useState<number | null>(null);

  // Landing state: which hubs are wired up + featured skills.
  const [sources, setSources] = useState<SkillHubSource[]>([]);
  const [featured, setFeatured] = useState<SkillHubResult[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);

  // identifier -> installed entry (drives "Installed" badges).
  const [installed, setInstalled] = useState<
    Record<string, SkillHubInstalledEntry>
  >({});

  // Live action log for the most recent install/update.
  const [action, setAction] = useState<string | null>(null);
  const [actionLog, setActionLog] = useState<string[]>([]);
  const [actionRunning, setActionRunning] = useState(false);

  // Detail dialog (preview + scan for a single skill).
  const [detail, setDetail] = useState<SkillHubResult | null>(null);

  /* ---- Load connected hubs + featured skills on mount ---- */
  useEffect(() => {
    let cancelled = false;
    api
      .getSkillHubSources(profile)
      .then((r) => {
        if (cancelled) return;
        setSources(r.sources);
        setFeatured(r.featured);
        setInstalled(r.installed);
      })
      .catch(() => {
        /* leave landing minimal on failure */
      })
      .finally(() => {
        if (!cancelled) setSourcesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [profile]);

  /* ---- Search ---- */
  const runSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setSearched(true);
    const t0 = performance.now();
    try {
      const r = await api.searchSkillsHub(q, "all", 20, profile);
      setResults(r.results);
      setSourceCounts(r.source_counts || {});
      setTimedOut(r.timed_out || []);
      setInstalled((prev) => ({ ...prev, ...(r.installed || {}) }));
    } catch (e) {
      showToast(`Hub search failed: ${e}`, "error");
      setResults([]);
      setSourceCounts({});
      setTimedOut([]);
    } finally {
      setSearchMs(Math.round(performance.now() - t0));
      setSearching(false);
    }
  }, [query, showToast, profile]);

  /* ---- Poll a spawned action's log until it exits ---- */
  useEffect(() => {
    if (!action) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const st = await api.getActionStatus(action, 200);
        if (cancelled) return;
        setActionLog(st.lines);
        setActionRunning(st.running);
        if (st.running) {
          timer = setTimeout(poll, 1200);
        } else {
          // Install finished — refresh installed-state so badges update.
          api
            .getSkillHubSources(profile)
            .then((r) => !cancelled && setInstalled(r.installed))
            .catch(() => {});
        }
      } catch {
        if (!cancelled) setActionRunning(false);
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [action, profile]);

  const install = useCallback(
    async (identifier: string) => {
      try {
        const res = await api.installSkillFromHub(identifier, profile);
        showToast(`Installing ${identifier}…`, "success");
        setActionLog([]);
        setActionRunning(true);
        setAction(res.name);
        setDetail(null);
      } catch (e) {
        showToast(`Install failed: ${e}`, "error");
      }
    },
    [showToast, profile],
  );

  const updateAll = useCallback(async () => {
    try {
      const res = await api.updateSkillsFromHub(profile);
      showToast("Updating installed skills…", "success");
      setActionLog([]);
      setActionRunning(true);
      setAction(res.name);
    } catch (e) {
      showToast(`Update failed: ${e}`, "error");
    }
  }, [showToast, profile]);

  const isInstalled = useCallback(
    (identifier: string) => Boolean(installed[identifier]),
    [installed],
  );

  const showLanding = !searched && !searching;

  return (
    <div className="flex flex-col gap-3">
      {/* ── Search bar ── */}
      <Card className="rounded-none">
        <CardContent className="py-4 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                className="h-8 pl-8 text-sm"
                placeholder="Search the skill hub (GitHub, official, community)…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void runSearch();
                }}
              />
            </div>
            <Button
              size="sm"
              onClick={() => void runSearch()}
              disabled={searching || !query.trim()}
              prefix={searching ? <Spinner /> : <Search className="h-3.5 w-3.5" />}
            >
              Search
            </Button>
            <Button
              size="sm"
              outlined
              onClick={() => void updateAll()}
              prefix={<RefreshCw className="h-3.5 w-3.5" />}
            >
              Update all
            </Button>
          </div>

          {/* Connected hubs strip — proves the tab is wired up. */}
          <ConnectedHubs sources={sources} loading={sourcesLoading} />
        </CardContent>
      </Card>

      {/* ── Install/update action log (CAP10 reference implementation) ── */}
      {action && (
        <Card className="rounded-none">
          <CardContent className="py-3">
            <div className="flex items-center gap-2 mb-2">
              <Download className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="font-mono text-xs">{action}</span>
              {actionRunning ? (
                <Badge tone="warning">running</Badge>
              ) : (
                <Badge tone="success">done</Badge>
              )}
              {!actionRunning && (
                <Button
                  ghost
                  size="xs"
                  className="ml-auto text-muted-foreground"
                  onClick={() => setAction(null)}
                  aria-label="Dismiss"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words bg-background/50 border border-border p-2 text-xs font-mono text-muted-foreground">
              {actionLog.length ? actionLog.join("\n") : "Starting…"}
            </pre>
          </CardContent>
        </Card>
      )}

      {/* ── Landing: featured skills (before any search) ── */}
      {showLanding && (
        <>
          {sourcesLoading ? (
            <div aria-busy="true" className="flex flex-col gap-2 py-2">
              <Skeleton variant="row-list" rows={5} />
            </div>
          ) : featured.length > 0 ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 px-1">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                <span className="font-mondwest text-display text-xs tracking-[0.12em] text-text-secondary uppercase">
                  Featured skills
                </span>
                <span className="text-xs text-text-tertiary">
                  from the Fabric index — search above for thousands more
                </span>
              </div>
              {featured.map((r) => (
                <HubResultRow
                  key={r.identifier}
                  result={r}
                  installed={isInstalled(r.identifier)}
                  onOpen={() => setDetail(r)}
                  onInstall={() => void install(r.identifier)}
                />
              ))}
            </div>
          ) : (
            <Card className="rounded-none">
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                Search the hub above to browse installable skills from the
                connected sources.
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* ── Searching skeleton (CAP9 — no full-section spinner) ── */}
      {searching && (
        <div aria-busy="true" className="flex flex-col gap-2 py-2">
          <Skeleton variant="row-list" rows={5} />
        </div>
      )}

      {/* ── Search results ── */}
      {!searching && searched && (
        <>
          <SearchMeta
            count={results.length}
            sourceCounts={sourceCounts}
            timedOut={timedOut}
            ms={searchMs}
          />
          {results.length === 0 ? (
            <Card className="rounded-none">
              <EmptyState
                icon={Search}
                title="No matching skills found in the hub."
                description="Try a broader query — results fan out across every connected source."
              />
            </Card>
          ) : (
            results.map((r) => (
              <HubResultRow
                key={r.identifier}
                result={r}
                installed={isInstalled(r.identifier)}
                onOpen={() => setDetail(r)}
                onInstall={() => void install(r.identifier)}
              />
            ))
          )}
        </>
      )}

      {/* ── Detail dialog: preview + scan ── */}
      {detail && (
        <SkillDetailDialog
          result={detail}
          installed={isInstalled(detail.identifier)}
          onClose={() => setDetail(null)}
          onInstall={() => void install(detail.identifier)}
          showToast={showToast}
        />
      )}
    </div>
  );
}

/* ---- Connected hubs strip ---- */
function ConnectedHubs({
  sources,
  loading,
}: {
  sources: SkillHubSource[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <p className="text-xs text-muted-foreground">Connecting to skill hubs…</p>
    );
  }
  if (sources.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Results come from the same sources as{" "}
        <span className="font-mono">Fabric skills search</span>.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="flex items-center gap-1 text-xs text-text-tertiary">
        <Globe className="h-3 w-3" />
        Connected hubs:
      </span>
      {sources.map((s) => {
        const down =
          (s.id === "hermes-index" && s.available === false) ||
          (s.id === "github" && s.rate_limited === true);
        return (
          <Badge
            key={s.id}
            tone={down ? "outline" : "secondary"}
            className={cn("text-xs", down && "opacity-60")}
            title={
              s.id === "github" && s.rate_limited
                ? "GitHub API rate-limited — set GITHUB_TOKEN to raise the limit"
                : s.id === "hermes-index" && s.available === false
                  ? "Centralized index unavailable — falling back to live sources"
                  : undefined
            }
          >
            {s.label}
            {s.id === "github" && s.rate_limited ? " (rate-limited)" : ""}
          </Badge>
        );
      })}
    </div>
  );
}

/* ---- Search result-count + per-source breakdown ---- */
function SearchMeta({
  count,
  sourceCounts,
  timedOut,
  ms,
}: {
  count: number;
  sourceCounts: Record<string, number>;
  timedOut: string[];
  ms: number | null;
}) {
  const entries = Object.entries(sourceCounts).filter(([, n]) => n > 0);
  return (
    <div className="flex flex-wrap items-center gap-2 px-1 text-xs text-text-tertiary">
      <Badge tone="secondary" className="text-xs">
        {count} result{count !== 1 ? "s" : ""}
      </Badge>
      {ms != null && <span>{(ms / 1000).toFixed(1)}s</span>}
      {entries.length > 0 && (
        <span className="flex flex-wrap items-center gap-1.5">
          {entries.map(([sid, n]) => (
            <span key={sid} className="font-mono">
              {sid}:{n}
            </span>
          ))}
        </span>
      )}
      {timedOut.length > 0 && (
        <span className="flex items-center gap-1 text-warning">
          <AlertTriangle className="h-3 w-3" />
          {timedOut.join(", ")} timed out
        </span>
      )}
    </div>
  );
}

/* ---- One hub result — CapabilityRow consumer (K8) ---- */
function HubResultRow({
  result,
  installed,
  onOpen,
  onInstall,
}: {
  result: SkillHubResult;
  installed: boolean;
  onOpen: () => void;
  onInstall: () => void;
}) {
  const trust = trustVisual(result.trust_level);
  return (
    <CapabilityRow
      name={result.name}
      badges={
        <>
          <Badge tone={trust.tone} className="text-xs">
            {trust.label}
          </Badge>
          <Badge tone="secondary" className="text-xs">
            {result.source}
          </Badge>
          {installed && (
            <Badge tone="success" className="text-xs">
              installed
            </Badge>
          )}
        </>
      }
      description={result.description}
      meta={
        <>
          {result.tags.slice(0, 5).map((tag) => (
            <span
              key={tag}
              className="text-[0.65rem] text-text-tertiary border border-border px-1 py-px"
            >
              {tag}
            </span>
          ))}
          <span className="min-w-0 truncate text-text-tertiary" title={result.identifier}>
            {result.identifier}
          </span>
        </>
      }
      actions={
        <div className="flex shrink-0 flex-col gap-1.5">
          <Button
            size="sm"
            outlined
            onClick={onOpen}
            prefix={<FileText className="h-3.5 w-3.5" />}
            aria-label={`Open ${result.name}`}
          >
            Details
          </Button>
          {installed ? (
            <Button
              size="sm"
              ghost
              disabled
              prefix={<CheckCircle2 className="h-3.5 w-3.5" />}
            >
              Installed
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={onInstall}
              prefix={<Download className="h-3.5 w-3.5" />}
            >
              Install
            </Button>
          )}
        </div>
      }
    />
  );
}

/* ---- Detail dialog: SKILL.md preview + on-demand security scan ---- */
function SkillDetailDialog({
  result,
  installed,
  onClose,
  onInstall,
  showToast,
}: {
  result: SkillHubResult;
  installed: boolean;
  onClose: () => void;
  onInstall: () => void;
  showToast: (msg: string, kind: "success" | "error") => void;
}) {
  const [tab, setTab] = useState<"readme" | "scan">("readme");
  const [preview, setPreview] = useState<SkillHubPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [scan, setScan] = useState<SkillHubScan | null>(null);
  const [scanning, setScanning] = useState(false);
  const trust = trustVisual(result.trust_level);

  useEffect(() => {
    // Promise-chain shape (page idiom): setState fires only inside async
    // callbacks so the effect body stays lint-clean
    // (react-hooks/set-state-in-effect).
    let cancelled = false;
    Promise.resolve()
      .then(() => {
        if (cancelled) return null;
        setPreviewLoading(true);
        return api.previewSkillFromHub(result.identifier);
      })
      .then((p) => {
        if (!cancelled && p) setPreview(p);
      })
      .catch((e) => {
        if (!cancelled) showToast(`Preview failed: ${e}`, "error");
      })
      .finally(() => !cancelled && setPreviewLoading(false));
    return () => {
      cancelled = true;
    };
  }, [result.identifier, showToast]);

  const runScan = useCallback(async () => {
    setScanning(true);
    setTab("scan");
    try {
      const s = await api.scanSkillFromHub(result.identifier);
      setScan(s);
    } catch (e) {
      showToast(`Scan failed: ${e}`, "error");
    } finally {
      setScanning(false);
    }
  }, [result.identifier, showToast]);

  return (
    <Dialog open onOpenChange={(o: boolean) => !o && onClose()}>
      <DialogContent className="max-w-3xl rounded-none">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2 text-sm">
            <Package className="h-4 w-4" />
            {result.name}
            <Badge tone={trust.tone} className="text-xs">
              {trust.label}
            </Badge>
            <Badge tone="secondary" className="text-xs">
              {result.source}
            </Badge>
            {installed && (
              <Badge tone="success" className="text-xs">
                installed
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription className="sr-only">
            Preview the SKILL.md source and run a security scan for {result.name}{" "}
            before installing.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-1 flex flex-col gap-1">
          <p className="text-xs text-text-secondary">{result.description}</p>
          <p className="text-xs font-mono text-text-tertiary truncate">
            {result.identifier}
          </p>
        </div>

        {/* Action row */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-border py-2.5">
          <Button
            size="sm"
            outlined={tab !== "readme"}
            onClick={() => setTab("readme")}
            prefix={<FileText className="h-3.5 w-3.5" />}
          >
            Read SKILL.md
          </Button>
          <Button
            size="sm"
            outlined={tab !== "scan"}
            onClick={() => void runScan()}
            disabled={scanning}
            prefix={
              scanning ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
              ) : (
                <Shield className="h-3.5 w-3.5" />
              )
            }
          >
            {scan ? "Re-scan" : "Security scan"}
          </Button>
          <div className="ml-auto flex items-center gap-3">
            {result.repo && (
              <a
                href={`https://github.com/${result.repo}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                {result.repo}
              </a>
            )}
            {installed ? (
              <Button
                size="sm"
                ghost
                disabled
                prefix={<CheckCircle2 className="h-3.5 w-3.5" />}
              >
                Installed
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={onInstall}
                prefix={<Download className="h-3.5 w-3.5" />}
              >
                Install
              </Button>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="mt-3 max-h-[55vh] overflow-auto">
          {tab === "readme" ? (
            previewLoading ? (
              <div aria-busy="true" className="py-6">
                <Skeleton variant="row-list" rows={6} />
              </div>
            ) : preview ? (
              <div className="flex flex-col gap-2.5">
                {preview.tags.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1">
                    {preview.tags.map((tag) => (
                      <span
                        key={tag}
                        className="text-[0.65rem] font-mono text-text-tertiary border border-border px-1 py-px"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
                {preview.files.length > 0 && (
                  <div className="text-xs text-text-tertiary">
                    <span className="font-mondwest tracking-[0.1em] uppercase">
                      Files:{" "}
                    </span>
                    <span className="font-mono">{preview.files.join("  ")}</span>
                  </div>
                )}
                <pre className="whitespace-pre-wrap break-words bg-background/50 border border-border p-3 text-xs font-mono text-text-secondary leading-relaxed">
                  {(preview.skill_md || "").trim() || "(SKILL.md is empty)"}
                </pre>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-10">
                Couldn't load the skill source.
              </p>
            )
          ) : (
            <ScanPanel scan={scan} scanning={scanning} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ---- Visual security-scan result ---- */
function ScanPanel({
  scan,
  scanning,
}: {
  scan: SkillHubScan | null;
  scanning: boolean;
}) {
  if (scanning && !scan) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12">
        <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-primary" />
        <span className="text-xs text-muted-foreground">
          Fetching, quarantining, and scanning…
        </span>
      </div>
    );
  }
  if (!scan) {
    return (
      <p className="text-sm text-muted-foreground text-center py-10">
        Run a security scan to inspect this skill for risky patterns before
        installing.
      </p>
    );
  }

  const v = verdictVisual(scan.verdict);
  const policyTone =
    scan.policy === "allow"
      ? "success"
      : scan.policy === "ask"
        ? "warning"
        : "destructive";
  const policyLabel =
    scan.policy === "allow"
      ? "Install allowed"
      : scan.policy === "ask"
        ? "Needs confirmation"
        : "Install blocked";

  return (
    <div className="flex flex-col gap-3">
      {/* Verdict header */}
      <div className="flex flex-wrap items-center gap-2 border border-border p-3">
        <v.Icon
          className={cn(
            "h-6 w-6",
            scan.verdict === "safe"
              ? "text-success"
              : scan.verdict === "dangerous"
                ? "text-destructive"
                : "text-warning",
          )}
        />
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Verdict: {v.label}</span>
            <Badge tone={v.tone} className="text-xs">
              {scan.verdict}
            </Badge>
          </div>
          <span className="text-xs text-text-tertiary">
            {scan.trust_level} source · {scan.findings.length} finding
            {scan.findings.length !== 1 ? "s" : ""}
          </span>
        </div>
        <Badge tone={policyTone} className="ml-auto text-xs">
          {policyLabel}
        </Badge>
      </div>

      {/* Severity tally */}
      <div className="flex flex-wrap items-center gap-1.5">
        {(["critical", "high", "medium", "low"] as const).map((sev) => {
          const n = scan.severity_counts[sev] || 0;
          if (n === 0) return null;
          return (
            <Badge key={sev} tone={SEVERITY_TONE[sev]} className="text-xs">
              {n} {sev}
            </Badge>
          );
        })}
        {scan.findings.length === 0 && (
          <span className="flex items-center gap-1 text-xs text-success">
            <CheckCircle2 className="h-3.5 w-3.5" />
            No risky patterns detected
          </span>
        )}
      </div>

      <p className="text-xs text-text-tertiary">{scan.policy_reason}</p>

      {/* Findings */}
      {scan.findings.length > 0 && (
        <div className="flex flex-col border border-border divide-y divide-border">
          {scan.findings.map((f, i) => (
            <div key={i} className="flex items-start gap-2 p-2">
              <Badge
                tone={SEVERITY_TONE[f.severity] || "outline"}
                className="text-xs shrink-0"
              >
                {f.severity}
              </Badge>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-medium">{f.category}</span>
                  <span className="text-xs font-mono text-text-tertiary truncate">
                    {f.file}:{f.line}
                  </span>
                </div>
                <p className="text-xs text-text-secondary">{f.description}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
