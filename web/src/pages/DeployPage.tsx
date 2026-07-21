import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  ClipboardList,
  Laptop,
  Package,
  Rocket,
  RotateCcw,
  Server,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Badge, type BadgeTone } from "@/components/fabric/Badge";
import { EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type {
  LoomDeployment,
  LoomHost,
  LoomProject,
  LoomStatus,
} from "@/lib/api";

/**
 * DEPLOY — a guided, non-technical surface over the Loom deploy plane.
 *
 * Three plain-language steps (where to run it → what to deploy → deploy),
 * a status header, and a deployments ledger with rollback. Every deploy is
 * previewed as a plan first, so nothing runs until the user confirms.
 */

type ProjectKind = "compose" | "fabric-hosted";

/** Friendly, non-technical name for a project kind. */
function kindLabel(kind: string): string {
  if (kind === "fabric-hosted") return "Host Fabric itself";
  if (kind === "compose") return "A Docker Compose app";
  return kind;
}

/** Map a deployment/host state onto a Badge tone. */
function stateTone(state: string): BadgeTone {
  const s = state.toLowerCase();
  if (s === "active" || s === "ready" || s === "online") return "success";
  if (s === "failed" || s === "error" || s === "offline") return "destructive";
  if (s === "planned") return "secondary";
  if (s === "deploying" || s === "pending" || s === "running") return "warning";
  return "outline";
}

/**
 * fetchJSON throws ``Error("<status>: <body>")``; the backend body is
 * ``{ detail: { code, message } }``. Surface the human ``message`` when we
 * can parse it, otherwise the raw error text.
 */
function errorMessage(e: unknown): string {
  if (!(e instanceof Error)) return String(e);
  const sep = e.message.indexOf(": ");
  const body = sep >= 0 ? e.message.slice(sep + 2) : e.message;
  try {
    const parsed = JSON.parse(body) as { detail?: { message?: string } };
    if (parsed?.detail?.message) return parsed.detail.message;
  } catch {
    /* not JSON — fall through to the raw message */
  }
  return e.message;
}

export default function DeployPage() {
  const { toast, showToast } = useToast();

  const [status, setStatus] = useState<LoomStatus | null>(null);
  const [hosts, setHosts] = useState<LoomHost[]>([]);
  const [projects, setProjects] = useState<LoomProject[]>([]);
  const [deployments, setDeployments] = useState<LoomDeployment[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // "Add a project" form.
  const [projName, setProjName] = useState("");
  const [projKind, setProjKind] = useState<ProjectKind>("compose");
  const [projSource, setProjSource] = useState("");
  const [projCompose, setProjCompose] = useState("");
  const [projHealth, setProjHealth] = useState("");

  // Deploy step selections + the plan/result cycle.
  const [selectedProject, setSelectedProject] = useState("");
  const [selectedHost, setSelectedHost] = useState("");
  const [plan, setPlan] = useState<LoomDeployment | null>(null);
  const [result, setResult] = useState<LoomDeployment | null>(null);

  // Per-action busy flags.
  const [addingHost, setAddingHost] = useState(false);
  const [addingProject, setAddingProject] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [rollingBack, setRollingBack] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.getLoomStatus(),
      api.getLoomHosts(),
      api.getLoomProjects(),
      api.getLoomDeployments(),
    ])
      .then(([s, h, p, d]) => {
        setStatus(s);
        setHosts(h);
        setProjects(p);
        setDeployments(d);
        setLoadError(null);
      })
      .catch((e) => setLoadError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // A previewed plan is bound to the project + host it was planned for.
  // Whenever either selection changes, that plan no longer describes the
  // chosen target — drop it (and any stale result) so the user must
  // re-preview before deploying. This is what stops "Deploy now" from
  // applying a plan for a different target.
  useEffect(() => {
    setPlan(null);
    setResult(null);
  }, [selectedProject, selectedHost]);

  const projectName = useCallback(
    (id: string) => projects.find((p) => p.id === id)?.name ?? id,
    [projects],
  );
  const hostName = useCallback(
    (id: string) => hosts.find((h) => h.id === id)?.name ?? id,
    [hosts],
  );

  // A local host we can offer "Use this machine" against, if any.
  const localHost = useMemo(
    () => hosts.find((h) => h.kind === "local" || h.name === "this-machine"),
    [hosts],
  );

  // Projects that have more than one deployment (or a prior version) can be
  // rolled back. Keyed by project id.
  const projectsWithHistory = useMemo(() => {
    const counts = new Map<string, number>();
    const hasPrev = new Set<string>();
    for (const d of deployments) {
      counts.set(d.project_id, (counts.get(d.project_id) ?? 0) + 1);
      if (d.previous_id) hasPrev.add(d.project_id);
    }
    const set = new Set<string>();
    for (const [id, count] of counts) {
      if (count > 1 || hasPrev.has(id)) set.add(id);
    }
    return set;
  }, [deployments]);

  const addThisMachine = async () => {
    setAddingHost(true);
    try {
      await api.createLoomHost({ name: "this-machine", kind: "local" });
      showToast("This machine is ready to use", "success");
      load();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setAddingHost(false);
    }
  };

  const addProject = async () => {
    const name = projName.trim();
    if (!name) return;
    setAddingProject(true);
    try {
      const config: Record<string, unknown> = {};
      if (projCompose.trim()) config.compose_file = projCompose.trim();
      if (projHealth.trim()) config.health_url = projHealth.trim();
      await api.createLoomProject({
        name,
        kind: projKind,
        source: projSource.trim() || undefined,
        config: Object.keys(config).length ? config : undefined,
      });
      showToast(`Added "${name}"`, "success");
      setProjName("");
      setProjSource("");
      setProjCompose("");
      setProjHealth("");
      load();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setAddingProject(false);
    }
  };

  const doPlan = async () => {
    if (!selectedProject || !selectedHost) return;
    setPlanning(true);
    setResult(null);
    setPlan(null);
    try {
      const dep = await api.planLoomDeploy({
        project: selectedProject,
        host: selectedHost,
      });
      setPlan(dep);
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setPlanning(false);
    }
  };

  const doDeploy = async () => {
    // Apply the exact deployment the user previewed — not a fresh replan — so
    // what runs is what was reviewed (plan-before-mutation). The plan is
    // cleared whenever the selected project/host changes, so a plan present
    // here is guaranteed to match the current target.
    if (!plan) return;
    setDeploying(true);
    try {
      const dep = await api.loomApply(plan.id, {
        // The user has already reviewed the plan; if it included destructive
        // steps, confirming here is the explicit go-ahead.
        allow_destructive: plan.plan?.has_destructive ?? false,
      });
      setResult(dep);
      setPlan(null);
      showToast(
        dep.state === "active"
          ? "Your app is live"
          : dep.state === "failed"
            ? "Deployment failed"
            : `Deployment ${dep.state}`,
        dep.state === "failed" ? "error" : "success",
      );
      load();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setDeploying(false);
    }
  };

  const doRollback = async (projectId: string, hostId: string) => {
    setRollingBack(projectId);
    try {
      const dep = await api.loomRollback({ project: projectId, host: hostId });
      setResult(dep);
      showToast("Rolled back to the previous version", "success");
      load();
    } catch (e) {
      showToast(errorMessage(e), "error");
    } finally {
      setRollingBack(null);
    }
  };

  if (loading && !status) {
    return (
      <div aria-busy="true" aria-live="polite" className="flex flex-col gap-6">
        <span className="sr-only">Loading</span>
        <Skeleton variant="block" className="h-28" />
        <Skeleton variant="block" className="h-48" />
        <Skeleton variant="block" className="h-48" />
      </div>
    );
  }

  if (loadError && !status) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center justify-between gap-2 border border-destructive/40 bg-destructive/10 px-3 py-2">
          <p className="text-xs text-destructive">
            Could not load your deployments: {loadError}
          </p>
          <Button outlined size="sm" onClick={load}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const activeResult = result;

  return (
    <div className="flex flex-col gap-8">
      <Toast toast={toast} />

      {/* Intro / reassurance */}
      <div className="flex flex-col gap-1">
        <p className="text-sm text-muted-foreground">
          Put something online in a few clicks. Pick where it should run,
          choose what to deploy, and press Deploy.
        </p>
        <p className="flex items-center gap-1.5 text-xs text-text-tertiary">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          You&apos;ll see exactly what will happen before anything runs.
        </p>
      </div>

      {/* ── Status header ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <Rocket className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Overview</CardTitle>
          </div>
          <CardDescription>
            Where things run, what you can deploy, and what&apos;s live now.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 p-5">
          <div className="grid grid-cols-3 gap-3">
            <div className="border border-border p-3">
              <div className="text-2xl font-semibold tabular-nums">
                {status?.hosts ?? 0}
              </div>
              <div className="text-xs text-text-tertiary">Machines</div>
            </div>
            <div className="border border-border p-3">
              <div className="text-2xl font-semibold tabular-nums">
                {status?.projects ?? 0}
              </div>
              <div className="text-xs text-text-tertiary">Projects</div>
            </div>
            <div className="border border-border p-3">
              <div className="text-2xl font-semibold tabular-nums">
                {status?.deployments ?? 0}
              </div>
              <div className="text-xs text-text-tertiary">Deployments</div>
            </div>
          </div>

          {status && status.active.length > 0 ? (
            <div className="flex flex-col gap-2">
              <p className="text-xs font-medium text-text-secondary">
                Live now
              </p>
              {status.active.map((a) => (
                <div
                  key={a.deployment}
                  className="flex flex-wrap items-center justify-between gap-2 border border-border p-3 text-sm"
                >
                  <span className="flex items-center gap-2">
                    <Package
                      className="h-4 w-4 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <span className="font-medium">
                      {projectName(a.project_id)}
                    </span>
                    <span className="text-text-tertiary">
                      on {hostName(a.host_id)}
                    </span>
                  </span>
                  <Badge tone={stateTone(a.state)}>{a.state}</Badge>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-text-tertiary">
              Nothing is running yet. Follow the steps below to deploy your
              first app.
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Step 1: Choose where to run it ────────────────────────────── */}
      <Card>
        <CardHeader className="border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <Server className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">
              Step 1 &middot; Choose where to run it
            </CardTitle>
          </div>
          <CardDescription>
            A machine is a computer that runs your app. The simplest option is
            this one.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 p-5">
          <div>
            <Button
              size="sm"
              onClick={() => void addThisMachine()}
              disabled={addingHost || !!localHost}
              prefix={addingHost ? <Spinner /> : <Laptop />}
            >
              {localHost ? "This machine is ready" : "Use this machine"}
            </Button>
          </div>

          {hosts.length === 0 ? (
            <EmptyState
              icon={Server}
              title="No machines yet"
              description="Add this machine above to get started."
            />
          ) : (
            <div className="flex flex-col gap-2">
              {hosts.map((h) => (
                <div
                  key={h.id}
                  className="flex flex-wrap items-center justify-between gap-2 border border-border p-3 text-sm"
                >
                  <span className="flex items-center gap-2">
                    {h.kind === "local" ? (
                      <Laptop
                        className="h-4 w-4 text-muted-foreground"
                        aria-hidden="true"
                      />
                    ) : (
                      <Server
                        className="h-4 w-4 text-muted-foreground"
                        aria-hidden="true"
                      />
                    )}
                    <span className="font-medium">{h.name}</span>
                    <span className="text-text-tertiary">
                      {h.kind === "local"
                        ? "this machine"
                        : (h.address || "remote machine")}
                    </span>
                  </span>
                  {h.state ? (
                    <Badge tone={stateTone(h.state)}>{h.state}</Badge>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Step 2: Choose what to deploy ─────────────────────────────── */}
      <Card>
        <CardHeader className="border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <Boxes className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">
              Step 2 &middot; Choose what to deploy
            </CardTitle>
          </div>
          <CardDescription>
            A project is the thing you want to put online.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5 p-5">
          {projects.length === 0 ? (
            <EmptyState
              icon={Package}
              title="No projects yet"
              description="Add your first project using the form below."
            />
          ) : (
            <div className="flex flex-col gap-2">
              {projects.map((p) => (
                <div
                  key={p.id}
                  className="flex flex-wrap items-center justify-between gap-2 border border-border p-3 text-sm"
                >
                  <span className="flex items-center gap-2">
                    <Package
                      className="h-4 w-4 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <span className="font-medium">{p.name}</span>
                  </span>
                  <Badge tone="secondary">{kindLabel(p.kind)}</Badge>
                </div>
              ))}
            </div>
          )}

          <div className="border border-border p-4">
            <p className="mb-3 text-sm font-medium">Add a project</p>
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="deploy-proj-name">Name</Label>
                <Input
                  id="deploy-proj-name"
                  placeholder="my-app"
                  value={projName}
                  onChange={(e) => setProjName(e.target.value)}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="deploy-proj-kind">What kind of app is it?</Label>
                <Select
                  id="deploy-proj-kind"
                  value={projKind}
                  onValueChange={(v) => setProjKind(v as ProjectKind)}
                >
                  <SelectOption value="compose">
                    A Docker Compose app
                  </SelectOption>
                  <SelectOption value="fabric-hosted">
                    Host Fabric itself
                  </SelectOption>
                </Select>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="deploy-proj-source">
                  Where is it? (optional)
                </Label>
                <Input
                  id="deploy-proj-source"
                  placeholder="/path/to/your/app"
                  value={projSource}
                  onChange={(e) => setProjSource(e.target.value)}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="deploy-proj-compose">
                  Compose file (optional)
                </Label>
                <Input
                  id="deploy-proj-compose"
                  placeholder="docker-compose.yml"
                  value={projCompose}
                  onChange={(e) => setProjCompose(e.target.value)}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="deploy-proj-health">
                  Health check URL (optional)
                </Label>
                <Input
                  id="deploy-proj-health"
                  placeholder="http://localhost:8080/health"
                  value={projHealth}
                  onChange={(e) => setProjHealth(e.target.value)}
                />
              </div>

              <div className="flex justify-end">
                <Button
                  size="sm"
                  onClick={() => void addProject()}
                  disabled={addingProject || !projName.trim()}
                  prefix={addingProject ? <Spinner /> : undefined}
                >
                  {addingProject ? "Adding..." : "Add a project"}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Step 3: Deploy ────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <Rocket className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Step 3 &middot; Deploy</CardTitle>
          </div>
          <CardDescription>
            Pick a project and a machine, preview the plan, then deploy.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="deploy-pick-project">Project</Label>
              <Select
                id="deploy-pick-project"
                value={selectedProject}
                placeholder="Choose a project"
                disabled={projects.length === 0}
                onValueChange={setSelectedProject}
              >
                {projects.map((p) => (
                  <SelectOption key={p.id} value={p.id}>
                    {p.name}
                  </SelectOption>
                ))}
              </Select>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="deploy-pick-host">Machine</Label>
              <Select
                id="deploy-pick-host"
                value={selectedHost}
                placeholder="Choose a machine"
                disabled={hosts.length === 0}
                onValueChange={setSelectedHost}
              >
                {hosts.map((h) => (
                  <SelectOption key={h.id} value={h.id}>
                    {h.name}
                  </SelectOption>
                ))}
              </Select>
            </div>
          </div>

          <div>
            <Button
              size="sm"
              outlined
              onClick={() => void doPlan()}
              disabled={planning || !selectedProject || !selectedHost}
              prefix={planning ? <Spinner /> : <ClipboardList />}
            >
              {planning ? "Preparing..." : "Preview the plan"}
            </Button>
          </div>

          {/* Plan preview → confirm to deploy */}
          {plan?.plan ? (
            <div className="flex flex-col gap-3 border border-border p-4">
              <div className="flex items-center gap-2">
                <ClipboardList
                  className="h-4 w-4 text-muted-foreground"
                  aria-hidden="true"
                />
                <p className="text-sm font-medium">Here&apos;s what will happen</p>
              </div>
              {plan.plan.summary ? (
                <p className="text-sm text-text-secondary">
                  {plan.plan.summary}
                </p>
              ) : null}
              <ol className="flex flex-col gap-2">
                {plan.plan.steps.map((step, i) => (
                  <li
                    key={`${step.action}-${i}`}
                    className="flex items-start gap-2 text-sm"
                  >
                    <span className="mt-0.5 text-xs text-text-tertiary tabular-nums">
                      {i + 1}.
                    </span>
                    <span className="flex flex-col">
                      <span className="font-medium">{step.action}</span>
                      {step.detail ? (
                        <span className="text-xs text-text-tertiary">
                          {step.detail}
                        </span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ol>

              {plan.plan.has_destructive ? (
                <p className="flex items-start gap-1.5 text-xs text-warning">
                  <AlertTriangle
                    className="mt-0.5 h-3.5 w-3.5 shrink-0"
                    aria-hidden="true"
                  />
                  Some steps will replace or remove things that already exist.
                </p>
              ) : null}

              <div className="flex justify-end">
                <Button
                  size="sm"
                  onClick={() => void doDeploy()}
                  disabled={deploying}
                  prefix={deploying ? <Spinner /> : <Rocket />}
                >
                  {deploying ? "Deploying..." : "Deploy now"}
                </Button>
              </div>
            </div>
          ) : null}

          {/* Deploy result */}
          {activeResult ? (
            <div className="flex flex-col gap-3 border border-border p-4">
              <div className="flex items-center gap-2">
                {activeResult.state === "failed" ? (
                  <AlertTriangle
                    className="h-4 w-4 text-destructive"
                    aria-hidden="true"
                  />
                ) : (
                  <CheckCircle2
                    className="h-4 w-4 text-success"
                    aria-hidden="true"
                  />
                )}
                <p className="text-sm font-medium">
                  {projectName(activeResult.project_id)} on{" "}
                  {hostName(activeResult.host_id)}
                </p>
                <Badge tone={stateTone(activeResult.state)}>
                  {activeResult.state}
                </Badge>
              </div>
              {activeResult.message ? (
                <p className="text-sm text-text-secondary">
                  {activeResult.message}
                </p>
              ) : null}
              {activeResult.logs ? (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap border border-border bg-background/40 p-3 font-courier text-xs">
                  {activeResult.logs}
                </pre>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ── Deployments ledger ────────────────────────────────────────── */}
      <Card>
        <CardHeader className="border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <Package className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Deployments</CardTitle>
          </div>
          <CardDescription>
            Everything you&apos;ve deployed, newest first.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-5">
          {deployments.length === 0 ? (
            <EmptyState
              icon={Package}
              title="No deployments yet"
              description="Your deployments will show up here once you deploy something."
            />
          ) : (
            <div className="flex flex-col gap-2">
              {deployments.map((d) => (
                <div
                  key={d.id}
                  className="flex flex-wrap items-center justify-between gap-2 border border-border p-3 text-sm"
                >
                  <span className="flex items-center gap-2">
                    <span className="font-medium">
                      {projectName(d.project_id)}
                    </span>
                    <span className="text-text-tertiary">
                      on {hostName(d.host_id)}
                    </span>
                    <Badge tone={stateTone(d.state)}>{d.state}</Badge>
                  </span>
                  {projectsWithHistory.has(d.project_id) ? (
                    <Button
                      size="xs"
                      outlined
                      onClick={() => void doRollback(d.project_id, d.host_id)}
                      disabled={rollingBack === d.project_id}
                      prefix={
                        rollingBack === d.project_id ? (
                          <Spinner />
                        ) : (
                          <RotateCcw />
                        )
                      }
                    >
                      {rollingBack === d.project_id
                        ? "Rolling back..."
                        : "Roll back"}
                    </Button>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
