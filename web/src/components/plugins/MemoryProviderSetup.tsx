import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { CopyButton } from "@nous-research/ui/ui/components/command-block";
import type {
  MemoryProviderInfo,
  MemoryProviderSetupInfo,
  MemoryProviderSetupResult,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Memory-provider dependency-setup surfaces (spec P3): the install-deps
 * hint, the per-step setup results block and the copyable setup command
 * blocks. Moved verbatim from `PluginsPage` in the P-requirements split —
 * the flows are frozen (N18); this file is layout-only extraction.
 */

function setupHasDetails(setup?: MemoryProviderSetupInfo) {
  if (!setup) return false;
  return Boolean(
    setup.external_dependencies?.length ||
      setup.pip_dependencies?.length ||
      setup.required_env?.length,
  );
}

function setupHasInstallableSteps(setup?: MemoryProviderSetupInfo) {
  if (!setup) return false;
  return Boolean(
    setup.external_dependencies?.some((dep) => dep.install) ||
      setup.pip_dependencies?.length,
  );
}

function SetupCommandBlock({ code, label }: { code: string; label: string }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[0.6875rem] text-muted-foreground">{label}</span>
        <CopyButton text={code} />
      </div>
      <div className="border border-border bg-background/40 px-3 py-2 font-mono text-[0.6875rem] leading-relaxed">
        <code className="break-all">{code}</code>
      </div>
    </div>
  );
}

function setupResultLabel(status: string) {
  if (status === "already_installed") return "already installed";
  if (status === "no_declared_steps") return "no declared setup";
  return status.replace(/_/g, " ");
}

function setupResultClass(status: string) {
  if (status === "failed") return "border-destructive/50 text-destructive";
  if (status === "installed" || status === "verified" || status === "already_installed") {
    return "border-success/50 text-success";
  }
  if (status === "missing") return "border-warning/50 text-warning";
  return "border-border text-muted-foreground";
}

function MemoryProviderSetupResults({ results }: { results: MemoryProviderSetupResult[] }) {
  if (!results.length) return null;

  return (
    <div className="grid gap-2 border border-border bg-background/20 p-3">
      <p className="text-muted-foreground">Setup results</p>
      {results.map((result, index) => {
        const detail = result.stderr || result.stdout;
        return (
          <div key={`${result.kind}-${result.name}-${index}`} className="grid gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "border px-2 py-0.5 font-mono text-[0.6875rem]",
                  setupResultClass(result.status),
                )}
              >
                {setupResultLabel(result.status)}
              </span>
              <span className="text-muted-foreground">
                {result.name}
                {result.kind ? ` (${result.kind.replace(/_/g, " ")})` : ""}
              </span>
            </div>
            {result.command ? (
              <code className="block break-all border border-border bg-background/40 px-2 py-1 font-mono text-[0.6875rem]">
                {result.command}
              </code>
            ) : null}
            {detail ? (
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words border border-border bg-background/40 px-2 py-1 font-mono text-[0.6875rem] text-muted-foreground">
                {detail}
              </pre>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function MemoryProviderSetupHint({
  installing,
  onInstall,
  provider,
  results,
}: {
  installing: boolean;
  onInstall: () => void;
  provider: MemoryProviderInfo;
  results: MemoryProviderSetupResult[] | null;
}) {
  const setup = provider.setup;
  const hasDetails = setupHasDetails(setup);
  const hasInstallableSteps = setupHasInstallableSteps(setup);
  const dependenciesInstalled = setup?.dependencies_installed ?? !hasInstallableSteps;
  const hasResults = Boolean(results?.length);
  const needsDependencySetup = hasInstallableSteps && !dependenciesInstalled;
  const isBlocked = provider.status === "unavailable" && needsDependencySetup;
  const shouldShow =
    hasResults ||
    needsDependencySetup ||
    (provider.status === "unavailable" && hasDetails && !dependenciesInstalled);

  if (!shouldShow) return null;

  if (!hasDetails || !setup) {
    return (
      <p className="border border-destructive/50 px-3 py-2 text-xs text-destructive">
        This provider is installed but unavailable. It may need local dependencies or a manual setup step before Fabric can activate it.
      </p>
    );
  }

  return (
    <div
      className={cn(
        "grid gap-3 border px-3 py-3 text-xs text-foreground",
        isBlocked ? "border-destructive/50" : "border-border",
      )}
    >
      <p className={isBlocked ? "text-destructive" : "text-muted-foreground"}>
        {needsDependencySetup
          ? "Finish these setup steps before Fabric can activate this provider."
          : "Provider dependency setup completed."}
      </p>

      {needsDependencySetup ? (
        <Button
          className="w-fit uppercase"
          disabled={installing}
          onClick={onInstall}
          size="sm"
        >
          <span className="inline-flex items-center gap-2">
            {installing ? <Spinner /> : null}
            {installing ? "Installing provider dependencies" : "Install provider dependencies"}
          </span>
        </Button>
      ) : null}

      {installing ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Spinner /> Running provider setup. This may take a minute…
        </div>
      ) : null}

      {results ? <MemoryProviderSetupResults results={results} /> : null}

      {needsDependencySetup ? (
        <>
          {setup.external_dependencies.map((dep, index) => (
            <div key={`${dep.name || "dependency"}-${index}`} className="grid gap-2">
              <p className="text-muted-foreground">
                External dependency{dep.name ? `: ${dep.name}` : ""}
              </p>
              {dep.install ? (
                <SetupCommandBlock
                  label={dep.name ? `Install ${dep.name}` : "Install dependency"}
                  code={dep.install}
                />
              ) : null}
              {dep.check ? (
                <SetupCommandBlock
                  label={dep.name ? `Verify ${dep.name}` : "Verify dependency"}
                  code={dep.check}
                />
              ) : null}
            </div>
          ))}

          {setup.pip_dependencies.length ? (
            <div className="grid gap-2">
              <p className="text-muted-foreground">Python dependencies</p>
              <div className="flex flex-wrap gap-2">
                {setup.pip_dependencies.map((dep) => (
                  <code
                    key={dep}
                    className="border border-border bg-background/40 px-2 py-1 font-mono text-[0.6875rem]"
                  >
                    {dep}
                  </code>
                ))}
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {setup.required_env.length && needsDependencySetup ? (
        <div className="grid gap-2">
          <p className="text-muted-foreground">
            Required environment values. Fill the matching fields below, or set them in the Fabric environment.
          </p>
          <div className="flex flex-wrap gap-2">
            {setup.required_env.map((envKey) => (
              <code
                key={envKey}
                className="border border-border bg-background/40 px-2 py-1 font-mono text-[0.6875rem]"
              >
                {envKey}
              </code>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
