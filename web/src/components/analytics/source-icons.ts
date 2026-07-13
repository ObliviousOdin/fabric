import {
  Clock,
  Globe,
  Hash,
  MessageCircle,
  MessageSquare,
  Terminal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * Monochrome source glyphs (G11) for the Observe workload report — same
 * mapping as the Sessions ledger's `SessionRunRow` so a run keeps its
 * glyph across pages. The glyph carries the distinction; callers render
 * it muted (no per-source color).
 */
export const SOURCE_ICONS: Record<string, LucideIcon> = {
  cli: Terminal,
  telegram: MessageCircle,
  discord: Hash,
  slack: MessageSquare,
  whatsapp: Globe,
  cron: Clock,
};

export function sourceIcon(source: string | null | undefined): LucideIcon {
  return (source && SOURCE_ICONS[source]) || Globe;
}

/** `12456` → `12.5k` (R4 — token counters render compact, never raw). */
export function formatCompact(n: number): string {
  if (n >= 1_000_000)
    return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}

/** `$0.0123` under a dollar, `$1.23` above (S2 precedent). */
export function formatCost(cost: number): string {
  return `$${cost >= 1 ? cost.toFixed(2) : cost.toFixed(4)}`;
}
