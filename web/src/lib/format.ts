/**
 * Format a token count as a human-readable string (e.g. 1M, 128K, 4096).
 * Strips trailing ".0" for clean round numbers.
 */
export function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`;
  return String(n);
}

/**
 * M8 consolidation: token *totals* on the Models cards/stats and the
 * Observe analytics tables go through the same compact implementation as
 * capability context windows — one compact format, not three page-local
 * copies. (Round values render "1M"/"128K" rather than "1.0M".)
 */
export const formatTokens = formatTokenCount;

/**
 * Compact cost readout for model analytics: `$1.23` / `$0.012` / `$0.0004`
 * / `$0` — precision grows as the amount shrinks so tiny estimates stay
 * distinguishable (M8; moved verbatim from `ModelsPage`).
 */
export function formatCost(n: number): string {
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(3)}`;
  if (n > 0) return `$${n.toFixed(4)}`;
  return "$0";
}
