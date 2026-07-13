import type { LucideIcon } from "lucide-react";
import {
  Blocks,
  Brain,
  Code,
  Cpu,
  Eye,
  Globe,
  Paintbrush,
  Shield,
  Wrench,
  Zap,
} from "lucide-react";

/**
 * Skills-page display vocabulary (K-requirements): category prettifiers,
 * toolset glyphs and the provenance-chip mapping — pure module so the page
 * and the row components share one table (R18: unknown values render as
 * their raw string, never crash).
 */

/** Human-facing labels for categories whose auto-prettified form is wrong. */
export const CATEGORY_LABELS: Record<string, string> = {
  mlops: "MLOps",
  "mlops/cloud": "MLOps / Cloud",
  "mlops/evaluation": "MLOps / Evaluation",
  "mlops/inference": "MLOps / Inference",
  "mlops/models": "MLOps / Models",
  "mlops/training": "MLOps / Training",
  "mlops/vector-databases": "MLOps / Vector DBs",
  mcp: "MCP",
  "red-teaming": "Red Teaming",
  ocr: "OCR",
  p5js: "p5.js",
  ai: "AI",
  ux: "UX",
  ui: "UI",
};

export function prettyCategory(
  raw: string | null | undefined,
  generalLabel: string,
): string {
  if (!raw) return generalLabel;
  if (CATEGORY_LABELS[raw]) return CATEGORY_LABELS[raw];
  return raw
    .split(/[-_/]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const TOOLSET_ICONS: Record<string, LucideIcon> = {
  computer: Cpu,
  web: Globe,
  security: Shield,
  vision: Eye,
  design: Paintbrush,
  ai: Brain,
  integration: Blocks,
  code: Code,
  automation: Zap,
};

/** Monochrome glyph for a toolset by name substring; `Wrench` fallback. */
export function toolsetIcon(name: string): LucideIcon {
  const lower = name.toLowerCase();
  for (const [key, icon] of Object.entries(TOOLSET_ICONS)) {
    if (lower.includes(key)) return icon;
  }
  return Wrench;
}

/** Rail/chip ordering for the provenance filter (K2). */
export const PROVENANCE_ORDER = ["hub", "bundled", "agent"] as const;

/**
 * Provenance chip visual (K4): `hub` → secondary, `bundled`/`agent` →
 * outline; `agent` is labeled "custom" in UI copy (callers localize via
 * `t.skills.inventory`). Unknown values pass through as raw label (R18).
 */
export function provenanceVisual(provenance: string): {
  tone: "secondary" | "outline";
  label: string;
} {
  switch (provenance) {
    case "hub":
      return { tone: "secondary", label: "hub" };
    case "bundled":
      return { tone: "outline", label: "bundled" };
    case "agent":
      return { tone: "outline", label: "custom" };
    default:
      return { tone: "outline", label: provenance };
  }
}
