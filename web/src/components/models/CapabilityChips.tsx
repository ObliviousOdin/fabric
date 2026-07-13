import { Brain, Eye, Wrench } from "lucide-react";
import type { ModelsAnalyticsModelEntry } from "@/lib/api";

/**
 * Capability chip row (Tools/Vision/Reasoning/family) shared by the model
 * usage cards (M6) and the loadout's main-model row (M2 — chips resolve
 * from the already-fetched analytics entry match; no extra fetch). The
 * `bg-success/10` Tools chip is token-based and G10-compliant.
 */
export function CapabilityBadges({
  capabilities,
}: {
  capabilities: ModelsAnalyticsModelEntry["capabilities"];
}) {
  const hasAny =
    capabilities.supports_tools ||
    capabilities.supports_vision ||
    capabilities.supports_reasoning ||
    capabilities.model_family;
  if (!hasAny) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {capabilities.supports_tools && (
        <span className="inline-flex items-center gap-1 bg-success/10 px-1.5 py-0.5 text-xs font-medium text-success">
          <Wrench className="h-2.5 w-2.5" /> Tools
        </span>
      )}
      {capabilities.supports_vision && (
        <span className="inline-flex items-center gap-1 bg-muted px-1.5 py-0.5 text-xs font-medium text-text-secondary">
          <Eye className="h-2.5 w-2.5" /> Vision
        </span>
      )}
      {capabilities.supports_reasoning && (
        <span className="inline-flex items-center gap-1 bg-muted px-1.5 py-0.5 text-xs font-medium text-text-secondary">
          <Brain className="h-2.5 w-2.5" /> Reasoning
        </span>
      )}
      {capabilities.model_family && (
        <span className="inline-flex items-center bg-muted px-1.5 py-0.5 text-xs font-medium text-text-secondary">
          {capabilities.model_family}
        </span>
      )}
    </div>
  );
}
