import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Switch } from "@nous-research/ui/ui/components/switch";
import { cn, themedBody } from "@/lib/utils";

/** Leading Switch config — where toggling is the row's primary action. */
export interface CapabilityRowSwitch {
  checked: boolean;
  onChange(): void;
  /** Toggle write in flight — disables the Switch (existing busy-set idiom). */
  busy?: boolean;
  /**
   * Accessible name for the bare Switch control; defaults to the row name.
   * (A11y addition to the CAP3 contract — an unnamed switch is unusable
   * with a screen reader.)
   */
  ariaLabel?: string;
}

export interface CapabilityRowProps {
  /** Identity zone (CAP1.1). */
  name: string;
  /**
   * Mono identity by default — technical identifiers the user might type
   * or grep (skill names, MCP server names, plugin ids). Pass `false` for
   * genuinely human labels (toolset display labels).
   */
  mono?: boolean;
  /**
   * Truncation `title` override on the name span (defaults to `name`) —
   * for rows whose display name is a human label over a technical id
   * (channel platforms: name "Telegram", title "telegram" — H2).
   */
  nameTitle?: string;
  /** Monochrome glyph, muted (G11). */
  icon?: LucideIcon;
  /** State zone (CAP1.2): leading Switch where toggling is primary. */
  switch?: CapabilityRowSwitch;
  /** State + provenance Badges (caller-ordered, CAP1.2/CAP1.3). */
  badges?: ReactNode;
  /** Body: description line, `text-xs` muted, `line-clamp-2`. */
  description?: ReactNode;
  /** Usage-evidence / meta line (`·`-separated by caller), mono `tabular-nums`. */
  meta?: ReactNode;
  /** Full-width extra block (test results, env hints…) — the R21 escape
   *  hatch: consumers compose here instead of growing this interface. */
  detail?: ReactNode;
  /** Actions zone (CAP1.5): trailing cluster, destructive rightmost. */
  actions?: ReactNode;
  /** Disabled items: opacity on the body, never on the actions. */
  dimmed?: boolean;
  /** Expandable variant (RunRow idiom); omit `onToggle` for inert rows. */
  expanded?: boolean;
  onToggle?: () => void;
  /** Expansion body, rendered under a top border when `expanded`. */
  children?: ReactNode;
  /**
   * `ledger` removes per-item card chrome so inventories can read as one
   * continuous operational register inside a caller-owned ruled list.
   */
  variant?: "boxed" | "ledger";
  className?: string;
}

/**
 * The shared capability row (CAP3) — the five-zone grammar (identity /
 * state / provenance / usage evidence / actions) for skill rows, toolset
 * rows, plugin rows, MCP server rows and MCP/hub catalog rows: 1px
 * `border-border` box (or borderless inside a bordered list container —
 * caller strips it via `className`), hover tint, `[switch?] [icon?]
 * [name+badges / description / meta / detail] [actions]` grid with an
 * optional expansion body below. No fixed heights (G12).
 */
export function CapabilityRow({
  name,
  mono = true,
  nameTitle,
  icon: Icon,
  switch: switchProps,
  badges,
  description,
  meta,
  detail,
  actions,
  dimmed,
  expanded,
  onToggle,
  children,
  variant = "boxed",
  className,
}: CapabilityRowProps) {
  return (
    <div
      className={cn(
        "max-w-full min-w-0 overflow-hidden transition-colors",
        variant === "boxed" ? "border border-border" : "border-0",
        className,
      )}
    >
      <div
        className={cn(
          "flex flex-wrap items-start gap-3 transition-colors hover:bg-secondary/30 sm:flex-nowrap",
          variant === "ledger" ? "px-1 py-4 sm:px-2" : "p-3",
          onToggle &&
            "cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30",
        )}
        onClick={onToggle}
        // Expand/collapse must be keyboard-operable too. The guard keeps
        // Enter/Space on nested controls (Switch, action buttons) from
        // also toggling the row.
        role={onToggle ? "button" : undefined}
        tabIndex={onToggle ? 0 : undefined}
        aria-expanded={onToggle ? !!expanded : undefined}
        onKeyDown={
          onToggle
            ? (e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onToggle();
                }
              }
            : undefined
        }
      >
        {switchProps && (
          // stopPropagation on the wrapper (not the Switch itself — the DS
          // Switch routes clicks through onCheckedChange): toggling the
          // capability must never toggle expansion.
          <span
            className={cn(
              "flex shrink-0 items-center pt-0.5",
              switchProps.busy && "animate-pulse motion-reduce:animate-none",
            )}
            onClick={(e) => e.stopPropagation()}
          >
            <Switch
              checked={switchProps.checked}
              onCheckedChange={() => switchProps.onChange()}
              disabled={switchProps.busy}
              aria-label={switchProps.ariaLabel ?? name}
            />
          </span>
        )}
        {Icon && (
          <span
            className={cn(
              "shrink-0 pt-0.5 text-muted-foreground",
              dimmed && "opacity-60",
            )}
          >
            <Icon aria-hidden="true" className="h-4 w-4" />
          </span>
        )}
        <div
          className={cn(
            "flex min-w-0 flex-1 flex-col gap-1",
            dimmed && "opacity-60",
          )}
        >
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            {/* Long ids truncate with the full value in `title` (CAP1.1). */}
            <span
              title={nameTitle ?? name}
              className={cn(
                "min-w-0 truncate text-sm",
                mono ? "font-mono-ui" : themedBody,
              )}
            >
              {name}
            </span>
            {badges}
          </div>
          {description != null && (
            <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
              {description}
            </p>
          )}
          {meta != null && (
            <div className="font-mono-ui flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
              {meta}
            </div>
          )}
          {detail != null && <div className="min-w-0">{detail}</div>}
        </div>
        {actions && (
          <div className="flex w-full shrink-0 items-center justify-end gap-2 sm:w-auto sm:justify-start">
            {actions}
          </div>
        )}
      </div>
      {expanded && children != null && (
        <div
          className={cn(
            "border-t border-border",
            variant === "ledger" && "px-2",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}
