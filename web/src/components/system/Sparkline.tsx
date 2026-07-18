import { useMemo } from "react";

export interface SparklineProps {
  /** Oldest → newest samples. Fewer than 2 points renders a flat baseline. */
  values: number[];
  /** Fixed upper bound (e.g. 100 for a percentage); omit to autoscale. */
  max?: number;
  /** Fixed lower bound (default 0). */
  min?: number;
  height?: number;
  /** Color comes from `currentColor` — set it with a text-color class. */
  className?: string;
  ariaLabel?: string;
}

/**
 * Minimal dependency-free sparkline. Fluid width via a fixed viewBox +
 * `preserveAspectRatio="none"`; the stroke stays even with
 * `vectorEffect="non-scaling-stroke"`. Line + faint area fill, both in
 * `currentColor` so the caller controls tone (Y11/G11 — restrained accent).
 */
export function Sparkline({
  values,
  max,
  min,
  height = 26,
  className,
  ariaLabel,
}: SparklineProps) {
  const { line, area } = useMemo(() => {
    const n = values.length;
    const W = 100;
    const H = height;
    if (n === 0) {
      const mid = H / 2;
      return { line: `M0,${mid} L${W},${mid}`, area: "" };
    }
    const lo = min ?? Math.min(...values);
    const hi = max ?? Math.max(...values, lo + 1);
    const span = Math.max(hi - lo, 1e-6);
    const pad = 2;
    const xAt = (i: number) => (n === 1 ? W : (i / (n - 1)) * W);
    const yAt = (v: number) =>
      H - pad - ((Math.min(Math.max(v, lo), hi) - lo) / span) * (H - pad * 2);
    const pts = values.map(
      (v, i) => `${i ? "L" : "M"}${xAt(i).toFixed(2)},${yAt(v).toFixed(2)}`,
    );
    const linePath = pts.join(" ");
    return { line: linePath, area: `${linePath} L${W},${H} L0,${H} Z` };
  }, [values, max, min, height]);

  return (
    <svg
      className={className}
      width="100%"
      height={height}
      viewBox={`0 0 100 ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel}
      aria-hidden={ariaLabel ? undefined : true}
    >
      {area && <path d={area} fill="currentColor" opacity={0.11} />}
      <path
        d={line}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
