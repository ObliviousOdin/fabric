import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { Skeleton } from "@/components/ui";

export interface SystemSectionProps {
  icon: LucideIcon;
  title: string;
  /** Trailing header slot (e.g. the Shell hooks "New hook" button). */
  end?: ReactNode;
  /**
   * Section still waiting on its own fetch (Y14/R29): renders a
   * layout-shaped Skeleton instead of the body. Each section keys off its
   * own fetch settling — the slowest endpoint never blanks the console.
   */
  loading?: boolean;
  children?: ReactNode;
}

/** Standard SYSTEM console section: muted icon+heading row, per-section skeleton (Y14). */
export function SystemSection({
  icon: Icon,
  title,
  end,
  loading,
  children,
}: SystemSectionProps) {
  return (
    <section className="flex flex-col gap-3" aria-busy={loading || undefined}>
      {end != null ? (
        <div className="flex items-center justify-between">
          <H2
            variant="sm"
            className="flex items-center gap-2 text-muted-foreground"
          >
            <Icon className="h-4 w-4" /> {title}
          </H2>
          {end}
        </div>
      ) : (
        <H2
          variant="sm"
          className="flex items-center gap-2 text-muted-foreground"
        >
          <Icon className="h-4 w-4" /> {title}
        </H2>
      )}
      {loading ? <Skeleton variant="block" /> : children}
    </section>
  );
}
