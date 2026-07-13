import { formatTokens } from "@/lib/format";

/**
 * Stacked token bar (M6 usage-evidence zone, kept verbatim from the
 * pre-split ModelsPage): input/output/cache/reasoning shares of a model's
 * traffic. Colors come exclusively from the two `--series-*-token` theme
 * vars — the only sanctioned chart colors (O1).
 */
export function TokenBar({
  input,
  output,
  cacheRead,
  reasoning,
}: {
  input: number;
  output: number;
  cacheRead: number;
  reasoning: number;
}) {
  const total = input + output + cacheRead + reasoning;
  if (total === 0) return null;

  // Segments carry a CSS color value (`var(--token)` or a color-mix over
  // one) rather than a Tailwind class so the series can pick up the active
  // theme's `--series-*-token` vars — see `themes/types.ts`
  // `ThemeSeriesColors`. Cache reads are input-side and reasoning is
  // output-side, so both derive from the same two series tokens (mixed
  // toward the canvas) instead of introducing extra chromatic accents.
  const segments: Array<{ color: string; label: string; value: number }> = [
    {
      value: cacheRead,
      color:
        "color-mix(in srgb, var(--series-input-token) 45%, var(--background-base))",
      label: "Cache Read",
    },
    {
      value: reasoning,
      color:
        "color-mix(in srgb, var(--series-output-token) 45%, var(--background-base))",
      label: "Reasoning",
    },
    { value: input, color: "var(--series-input-token)", label: "Input" },
    { value: output, color: "var(--series-output-token)", label: "Output" },
  ].filter((s) => s.value > 0);

  return (
    <div className="space-y-1.5">
      {/* Stacked bar — segments fill proportionally to their share of total */}
      <div className="relative flex min-h-[1.5rem] w-full items-stretch overflow-hidden">
        {segments.map((s, i) => (
          <div
            key={i}
            className="relative flex items-center transition-all duration-300 motion-reduce:transition-none"
            style={{
              backgroundColor: `color-mix(in srgb, ${s.color} 70%, transparent)`,
              width: `${(s.value / total) * 100}%`,
            }}
          >
            {/* Stepped fill pattern overlay */}
            <div
              className="absolute inset-0 opacity-30"
              style={{
                backgroundImage:
                  "repeating-linear-gradient(to right, transparent 0 0.4rem, currentColor 0.4rem calc(0.4rem + 1px))",
              }}
            />
          </div>
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-secondary">
        {segments.map((s, i) => (
          <span key={i} className="flex items-center gap-1">
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: s.color }}
            />
            {s.label} {formatTokens(s.value)}
          </span>
        ))}
      </div>
    </div>
  );
}
