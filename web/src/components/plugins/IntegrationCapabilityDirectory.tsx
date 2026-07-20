import { ArrowRight, Network, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { CapabilityRow } from "@/components/ui";
import { useI18n } from "@/i18n";

const SKILLS_PATH = "/admin/integrations/skills";
const MCP_PATH = "/admin/integrations/mcp";

/**
 * The Integrations parent route owns three capability surfaces: plugins,
 * skills and MCP. Skills and MCP intentionally stay out of the primary nav,
 * so this compact ledger keeps those sibling routes discoverable in context.
 */
export function IntegrationCapabilityDirectory() {
  const { t } = useI18n();
  const copy = t.pluginsPage.agents?.directory;

  const destinations = [
    {
      action: copy?.skillsAction ?? "Browse skills",
      description:
        copy?.skillsDescription ??
        "Discover, activate, and create reusable skills for Fabric.",
      icon: Sparkles,
      name: copy?.skillsName ?? "Skills Hub",
      path: SKILLS_PATH,
    },
    {
      action: copy?.mcpAction ?? "Manage MCP",
      description:
        copy?.mcpDescription ??
        "Connect external tool servers and browse the MCP catalog.",
      icon: Network,
      name: copy?.mcpName ?? "MCP servers",
      path: MCP_PATH,
    },
  ] as const;

  return (
    <section
      aria-labelledby="integration-capabilities-heading"
      className="flex flex-col gap-3"
    >
      <div className="flex items-center gap-3">
        <span aria-hidden className="h-px w-6 bg-primary" />
        <h2
          className="text-sm font-semibold text-foreground"
          id="integration-capabilities-heading"
        >
          {copy?.heading ?? "Capability library"}
        </h2>
      </div>

      <ul className="divide-y divide-border/75 border-y border-border/80">
        {destinations.map((destination) => (
          <li key={destination.path}>
            <CapabilityRow
              actions={
                <Link
                  aria-label={`${destination.action}: ${destination.name}`}
                  className="inline-flex min-h-9 items-center gap-1.5 px-2 text-xs font-medium uppercase tracking-wide text-foreground underline decoration-border underline-offset-4 transition-colors hover:text-primary hover:decoration-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  to={destination.path}
                >
                  {destination.action}
                  <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                </Link>
              }
              description={destination.description}
              icon={destination.icon}
              mono={false}
              name={destination.name}
              variant="ledger"
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
