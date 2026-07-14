import { Link, useLocation } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { ScreenState } from "@/components/experience/ScreenState";
import type { ScreenStateKind } from "@/components/experience/screen-state";

interface PlaceholderDefinition {
  title: string;
  kind: Exclude<ScreenStateKind, "normal" | "loading">;
  description: string;
  actionLabel: string;
  actionPath: string;
}

const PLACEHOLDERS: Record<string, PlaceholderDefinition> = {
  "/workspace/work": {
    title: "Connect a durable Work Board",
    kind: "empty",
    description:
      "Fabric will show named agents, dependencies, handoffs, retries, approvals, and artifacts here when a compatible operations board plugin is enabled. Conversations are not silently treated as durable work.",
    actionLabel: "Manage plugins",
    actionPath: "/admin/integrations/plugins",
  },
  "/workspace/memory": {
    title: "Typed Memory ledger is not exposed by this runtime",
    kind: "degraded",
    description:
      "Provider health remains available in Admin. Facts, episodes, procedures, policies, candidates, conflicts, provenance, versions, retrieval history, and corrections appear here only when the selected provider declares those capabilities.",
    actionLabel: "Open system memory",
    actionPath: "/admin/system",
  },
  "/workspace/approvals": {
    title: "No durable approval queue is available",
    kind: "empty",
    description:
      "Fabric does not fabricate pending decisions from ephemeral tool prompts. Durable requests will appear here with policy, evidence, eligible approvers, expiry, and decision history.",
    actionLabel: "Open Work Board",
    actionPath: "/workspace/work",
  },
  "/workspace/activity": {
    title: "Unified activity is being connected",
    kind: "read-only",
    description:
      "Current logs remain available in Admin. This Workspace feed will activate when task, approval, automation, and agent events share a scoped cursor-based projection.",
    actionLabel: "View current logs",
    actionPath: "/admin/advanced/logs",
  },
};

const FALLBACK: PlaceholderDefinition = {
  title: "This experience is not available yet",
  kind: "empty",
  description:
    "The route is reserved in the new Fabric information architecture, but this runtime does not expose a truthful data contract for it yet.",
  actionLabel: "Return home",
  actionPath: "/workspace/home",
};

export default function WorkspacePlaceholderPage() {
  const { pathname } = useLocation();
  const normalizedPath = pathname.replace(/\/+$/, "") || "/";
  const definition = PLACEHOLDERS[normalizedPath] ?? FALLBACK;

  return (
    <div className="mx-auto flex min-h-[50vh] w-full max-w-3xl items-center justify-center py-8">
      <ScreenState
        className="w-full"
        kind={definition.kind}
        title={definition.title}
        description={definition.description}
        primaryAction={
          <Link
            to={definition.actionPath}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {definition.actionLabel}
            <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
          </Link>
        }
      />
    </div>
  );
}
