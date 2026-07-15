export type DesignArtifactKind =
  | "component-lab"
  | "dashboard"
  | "design-system"
  | "landing-page"
  | "prototype";

export type DesignFidelity = "high" | "wireframe";

export type DesignSystemPreset =
  | "claude"
  | "fabric"
  | "fresh"
  | "linear"
  | "project"
  | "stripe"
  | "vercel";

export interface DesignArtifactOption {
  description: string;
  id: DesignArtifactKind;
  label: string;
}

export interface DesignSystemOption {
  description: string;
  id: DesignSystemPreset;
  label: string;
}

export interface DesignRequest {
  artifact: DesignArtifactKind;
  brief: string;
  fidelity: DesignFidelity;
  system: DesignSystemPreset;
}

export const DESIGN_ARTIFACT_OPTIONS: readonly DesignArtifactOption[] = [
  {
    id: "prototype",
    label: "Interactive prototype",
    description: "A working flow with the important states and interactions.",
  },
  {
    id: "landing-page",
    label: "Landing page",
    description: "A focused product or campaign page with responsive behavior.",
  },
  {
    id: "dashboard",
    label: "Dashboard",
    description:
      "An operational or monitoring surface built around real tasks.",
  },
  {
    id: "component-lab",
    label: "Component lab",
    description:
      "A set of reusable components, variants, and interaction states.",
  },
  {
    id: "design-system",
    label: "Design system",
    description:
      "A persistent DESIGN.md contract with tokens, rules, and handoff.",
  },
];

export const DESIGN_SYSTEM_OPTIONS: readonly DesignSystemOption[] = [
  {
    id: "project",
    label: "Current project",
    description:
      "Use the repository's DESIGN.md, tokens, and components when present.",
  },
  {
    id: "fresh",
    label: "New direction",
    description: "Derive and lock a new visual direction from the brief.",
  },
  {
    id: "fabric",
    label: "Fabric",
    description:
      "Follow Fabric's existing desktop or dashboard visual language.",
  },
  {
    id: "linear",
    label: "Linear",
    description: "Use Fabric's Linear reference as visual vocabulary.",
  },
  {
    id: "stripe",
    label: "Stripe",
    description: "Use Fabric's Stripe reference as visual vocabulary.",
  },
  {
    id: "vercel",
    label: "Vercel",
    description: "Use Fabric's Vercel reference as visual vocabulary.",
  },
  {
    id: "claude",
    label: "Claude",
    description: "Use Fabric's Claude reference as visual vocabulary.",
  },
];

const ARTIFACT_INSTRUCTIONS: Record<DesignArtifactKind, string> = {
  "component-lab":
    "Build a component lab with reusable variants and meaningful interaction states.",
  dashboard:
    "Build a task-oriented dashboard with realistic data and the important operating states.",
  "design-system":
    "Create or evolve a persistent DESIGN.md design contract, then validate the resulting system.",
  "landing-page":
    "Build a responsive landing page with a clear narrative and working primary interactions.",
  prototype:
    "Build a working prototype of the core flow, including its important states and interactions.",
};

const SYSTEM_INSTRUCTIONS: Record<DesignSystemPreset, string> = {
  claude:
    "Load the Claude reference from popular-web-designs and use it as visual vocabulary without copying product identity.",
  fabric:
    "Match the current Fabric surface by inspecting its real tokens, components, and nearby screens before making UI choices.",
  fresh:
    "Propose a small set of distinct directions, lock one direction, and document its visual contract before building.",
  linear:
    "Load the Linear reference from popular-web-designs and use it as visual vocabulary without copying product identity.",
  project:
    "Use the current project's DESIGN.md when present. Otherwise infer the smallest honest contract from existing tokens and components.",
  stripe:
    "Load the Stripe reference from popular-web-designs and use it as visual vocabulary without copying product identity.",
  vercel:
    "Load the Vercel reference from popular-web-designs and use it as visual vocabulary without copying product identity.",
};

function normalizeBrief(value: string): string {
  return value
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 4_000);
}

export function buildDesignPrompt(request: DesignRequest): string {
  const brief = normalizeBrief(request.brief);
  const fidelity =
    request.fidelity === "wireframe" ? "Wireframe" : "High fidelity";

  return [
    `/design ${brief}`,
    `Deliverable: ${ARTIFACT_INSTRUCTIONS[request.artifact]} Fidelity: ${fidelity}.`,
    `Design system: ${SYSTEM_INSTRUCTIONS[request.system]}`,
    "Workflow: inspect source context, lock the direction, build the real artifact, critique and verify it, then hand off exact files. Keep major reusable decisions in DESIGN.md.",
  ].join("\n");
}
