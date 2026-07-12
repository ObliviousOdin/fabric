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
  defaultSortDir?: SortDirection;
  /** Keep the header row visible while the table body scrolls. */
  stickyHeader?: boolean;
  /**
   * Tighter cell paddings. Both densities use Tailwind spacing utilities,
   * which resolve against `--spacing` and therefore already scale with the
   * theme's `--theme-spacing-mul` density multiplier.
   */
  compact?: boolean;
  /** Rendered (full-width, under the header row) when `rows` is empty — typically an `<EmptyState />`. */
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  className?: string;
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

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  defaultSortKey,
  defaultSortDir = "desc",
  stickyHeader = false,
  compact = false,
  empty,
  onRowClick,
  className,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(defaultSortKey ?? null);
  const [sortDir, setSortDir] = useState<SortDirection>(defaultSortDir);

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

  const cellPad = compact
    ? "py-1 px-3 first:pl-0 last:pr-0"
    : "py-2 px-4 first:pl-0 last:pr-0";

  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className={cn("w-full text-sm", themedBody)}>
        <thead className={cn(stickyHeader && "sticky top-0 z-10 bg-card")}>
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
                    cellPad,
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
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="p-0">
                {empty}
              </td>
            </tr>
          ) : (
            sorted.map((row, i) => (
              <tr
                key={rowKey ? rowKey(row, i) : i}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(
                  "border-b border-border/50 transition-colors hover:bg-secondary/20",
                  onRowClick && "cursor-pointer",
                )}
              >
                {columns.map((col) => {
                  const value = row[col.key];
                  return (
                    <td
                      key={col.key}
                      className={cn(
                        cellPad,
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
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
