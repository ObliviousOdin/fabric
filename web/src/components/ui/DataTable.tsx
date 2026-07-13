import { useCallback, useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn, themedBody } from "@/lib/utils";

export type SortDirection = "asc" | "desc";

export interface DataTableColumn<T> {
  /** Row property this column reads (also the sort key). */
  key: keyof T & string;
  header: ReactNode;
  sortable?: boolean;
  align?: "left" | "center" | "right";
  /** Technical readout (ids, model names, token counts) — renders in the UI mono stack. */
  mono?: boolean;
  /** Custom cell renderer; defaults to `String(row[key])` with `—` for nullish. */
  render?: (row: T) => ReactNode;
  headerClassName?: string;
  cellClassName?: string;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  /** Stable row identity; defaults to the array index. */
  rowKey?: (row: T, index: number) => string | number;
  /** Initial sort column; omit to render rows in the given order until a header is clicked. */
  defaultSortKey?: keyof T & string;
}

const ALIGN_CLASS: Record<NonNullable<DataTableColumn<unknown>["align"]>, string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

/**
 * Comparator ported from AnalyticsPage's `useTableSort`: nullish values sort
 * last regardless of direction; everything else compares with `<`/`>`.
 */
function compareValues(aVal: unknown, bVal: unknown, dir: SortDirection): number {
  if (aVal === null || aVal === undefined) return 1;
  if (bVal === null || bVal === undefined) return -1;
  if (aVal === bVal) return 0;
  const cmp = (aVal as number | string) > (bVal as number | string) ? 1 : -1;
  return dir === "asc" ? cmp : -cmp;
}

// Tailwind spacing utilities resolve against `--spacing`, so cell paddings
// already scale with the theme's `--theme-spacing-mul` density multiplier.
const CELL_PAD = "py-2 px-4 first:pl-0 last:pr-0";

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  defaultSortKey,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(defaultSortKey ?? null);
  const [sortDir, setSortDir] = useState<SortDirection>("desc");

  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    return [...rows].sort((a, b) =>
      compareValues(a[sortKey as keyof T], b[sortKey as keyof T], sortDir),
    );
  }, [rows, sortKey, sortDir]);

  // Direction cycling: re-clicking the active column flips asc/desc; a new
  // column starts back at desc (biggest-first for the numeric columns these
  // tables are mostly made of).
  const toggle = useCallback(
    (key: string) => {
      if (key === sortKey) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir("desc");
      }
    },
    [sortKey],
  );

  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full text-sm", themedBody)}>
        <thead>
          <tr className="border-b border-border font-sans text-display text-xs uppercase tracking-[0.12em] text-muted-foreground">
            {columns.map((col) => {
              const active = col.sortable && col.key === sortKey;
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={
                    active
                      ? sortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                  className={cn(
                    CELL_PAD,
                    "font-medium",
                    ALIGN_CLASS[col.align ?? "left"],
                    col.headerClassName,
                  )}
                >
                  {col.sortable ? (
                    <button
                      type="button"
                      onClick={() => toggle(col.key)}
                      className="-mx-1 inline-flex cursor-pointer select-none items-center gap-1.5 rounded px-1 py-0.5 transition-colors hover:bg-muted/40"
                    >
                      {col.header}
                      {active ? (
                        sortDir === "asc" ? (
                          <ArrowUp className="h-3.5 w-3.5 shrink-0 text-foreground/80" />
                        ) : (
                          <ArrowDown className="h-3.5 w-3.5 shrink-0 text-foreground/80" />
                        )
                      ) : (
                        <ArrowUpDown className="h-3 w-3 shrink-0 text-text-tertiary" />
                      )}
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={rowKey ? rowKey(row, i) : i}
              className="border-b border-border/50 transition-colors hover:bg-secondary/20"
            >
              {columns.map((col) => {
                const value = row[col.key];
                return (
                  <td
                    key={col.key}
                    className={cn(
                      CELL_PAD,
                      ALIGN_CLASS[col.align ?? "left"],
                      col.mono && "font-mono-ui text-xs",
                      col.cellClassName,
                    )}
                  >
                    {col.render
                      ? col.render(row)
                      : value === null || value === undefined
                        ? "—"
                        : String(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
