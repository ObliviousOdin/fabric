/**
 * Shared dashboard primitives ("terminal-grade minimalism"): token-only
 * styling, 1px-border elevation, mono type for technical readouts, spacing
 * via Tailwind utilities so everything scales with `--theme-spacing-mul`.
 */

/**
 * Generic sortable table. Typed columns (`key`/`header`/`sortable`/`align`/
 * `mono`/`render`), client-side sorting with nulls-last semantics, chrome-idiom
 * header row, optional sticky header and compact density, and an `empty` slot
 * (typically an `<EmptyState />`).
 */
export { DataTable } from "./DataTable";
export type { DataTableColumn, DataTableProps, SortDirection } from "./DataTable";

/**
 * Centered muted empty placeholder: lucide icon slot + title + description +
 * optional action button. Used standalone in cards and as DataTable's `empty`
 * slot.
 */
export { EmptyState } from "./EmptyState";
export type { EmptyStateProps } from "./EmptyState";

/**
 * Token-based loading placeholder (`bg-muted` + `animate-pulse`, no shimmer
 * gradients). Variants: `line`, `block`, `row-list` (n stacked lines).
 */
export { Skeleton } from "./Skeleton";
export type { SkeletonProps, SkeletonVariant } from "./Skeleton";

/**
 * Standard page toolbar row for `PageHeaderProvider` slots and in-page filter
 * rows — filters cluster leading, actions trailing, wraps on narrow widths.
 */
export { PageToolbar } from "./PageToolbar";
export type { PageToolbarProps } from "./PageToolbar";
