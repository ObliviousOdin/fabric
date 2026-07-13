import type { ComponentProps } from "react";
import type { Badge } from "@nous-research/ui/ui/components/badge";
import type { ProviderValidateResponse } from "@/lib/api";

type BadgeTone = NonNullable<ComponentProps<typeof Badge>["tone"]>;

/**
 * Keys with a server-side live probe (E7). Must match
 * `fabric_cli/web_server.py::_CREDENTIAL_PROBES` plus its `OPENAI_BASE_URL`
 * compatibility branch (R28 mirror — keep adjacent). Keys absent from the
 * server map never render a Test action: no fake coverage.
 */
export const PROVIDER_PROBE_KEYS: ReadonlySet<string> = new Set([
  "OPENROUTER_API_KEY",
  "OPENAI_API_KEY",
  "XAI_API_KEY",
  "GEMINI_API_KEY",
  "OPENAI_BASE_URL",
]);

/**
 * Last-outcome chip for a provider-key probe (the MCP `/test` precedent,
 * CAP2 outcome-chip row). `kind` lets callers localize the two fixed labels
 * (accepted / unreachable) while rejected keeps the server's message as the
 * load-bearing detail. Session-local — never persisted.
 */
export interface ProviderProbeOutcome {
  kind: "accepted" | "unreachable" | "rejected";
  tone: BadgeTone;
  /** English chip label; callers may localize `accepted`/`unreachable`. */
  label: string;
  /** Server detail line (may be empty). */
  message: string;
}

/**
 * Map a `POST /api/providers/validate` response onto the outcome chip:
 * `ok` → success (with the model count when the base-URL branch served a
 * catalog); `reachable: false` → warning, not destructive — the probe could
 * not run, which is not proof the value is bad (the server docstring says
 * callers may warn rather than hard-block an offline user); otherwise the
 * provider rejected the value → destructive + server message.
 */
export function providerProbeOutcome(
  res: ProviderValidateResponse,
): ProviderProbeOutcome {
  if (res.ok) {
    const models = res.models?.length;
    return {
      kind: "accepted",
      tone: "success",
      label:
        models != null
          ? `accepted · ${models} model${models === 1 ? "" : "s"}`
          : "key accepted",
      message: res.message,
    };
  }
  if (!res.reachable) {
    return {
      kind: "unreachable",
      tone: "warning",
      label: "could not reach provider",
      message: res.message,
    };
  }
  return {
    kind: "rejected",
    tone: "destructive",
    label: "rejected",
    message: res.message,
  };
}
