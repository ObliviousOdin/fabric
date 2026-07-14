import { NavLink } from "react-router-dom";
import { BriefcaseBusiness, ShieldCheck } from "lucide-react";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

export interface ExperienceSwitcherProps {
  surface: "workspace" | "admin";
  collapsed: boolean;
  onNavigate?: () => void;
}

const EXPERIENCES = [
  {
    id: "workspace" as const,
    labelKey: "workspace" as const,
    fallback: "Workspace",
    path: "/workspace/home",
    icon: BriefcaseBusiness,
  },
  {
    id: "admin" as const,
    labelKey: "admin" as const,
    fallback: "Admin",
    path: "/admin/ai-runtime/models",
    icon: ShieldCheck,
  },
] as const;

/** Keeps the operator and administrator information architectures explicit. */
export function ExperienceSwitcher({
  surface,
  collapsed,
  onNavigate,
}: ExperienceSwitcherProps) {
  const { t } = useI18n();
  const labels = t.app.enterpriseNav;
  return (
    <div
      aria-label={labels?.experience ?? "Fabric experience"}
      className={cn(
        "grid border-b border-border/70",
        collapsed ? "grid-cols-1 py-1" : "grid-cols-2 px-3",
      )}
      role="group"
    >
      {EXPERIENCES.map((experience) => {
        const Icon = experience.icon;
        const selected = surface === experience.id;
        const label = labels?.[experience.labelKey] ?? experience.fallback;
        return (
          <NavLink
            key={experience.id}
            to={experience.path}
            onClick={onNavigate}
            aria-current={selected ? "page" : undefined}
            aria-label={collapsed ? label : undefined}
            title={collapsed ? label : undefined}
            className={cn(
              "relative flex min-h-11 items-center justify-center gap-2 px-2 text-xs font-medium",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
              selected
                ? "text-foreground after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-primary"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
            )}
          >
            <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        );
      })}
    </div>
  );
}

export default ExperienceSwitcher;
