import { GatewayRpcError, type GatewayRpcErrorKind } from "./json-rpc-gateway";

/**
 * The typed-error taxonomy every gateway feature family classifies into, so
 * fail-closed UI can separate "gateway can't" from "was denied" from "try
 * again". Canonical order and content live in
 * apps/mobile/contracts/gateway-error-taxonomy-v1.json (a parity test asserts
 * equality with the fixture).
 */
export const GATEWAY_ERROR_CLASSES = [
  "unsupported",
  "denied",
  "transient",
  "needs_reauth",
  "reset_required",
  "contract_invalid",
  "unknown",
] as const;

export type GatewayErrorClass = (typeof GATEWAY_ERROR_CLASSES)[number];

/**
 * JSON-RPC error codes with a known classification. Extends the
 * `-32601 ⇒ unsupported` and `5040 ⇒ can't-capture` precedent; `-32047` is the
 * cursor/ledger reset shape (see parseWorkCursorReset in work-contract.ts).
 */
export const GATEWAY_RPC_ERROR_CODE_CLASSES: Readonly<
  Record<number, GatewayErrorClass>
> = {
  [-32601]: "unsupported",
  [-32047]: "reset_required",
  5040: "unsupported",
};

/**
 * Non-rpc transport failures are all retryable: nothing about the request was
 * judged, the bytes just never round-tripped.
 */
export const GATEWAY_TRANSPORT_KIND_CLASSES: Readonly<
  Record<Exclude<GatewayRpcErrorKind, "rpc">, GatewayErrorClass>
> = {
  aborted: "transient",
  closed: "transient",
  connect: "transient",
  send: "transient",
  timeout: "transient",
};

/**
 * Classify a failure from the gateway into the typed-error taxonomy.
 *
 * A GatewayRpcError with kind "rpc" maps by its code; every unmapped code —
 * and any value that is not a GatewayRpcError at all — is "unknown", which UIs
 * render as an honest error with the raw message and never retry silently.
 * Other kinds map through GATEWAY_TRANSPORT_KIND_CLASSES.
 *
 * needs_reauth and denied have no producing codes yet: they are reserved for
 * the new optional families (trust_center, node_invoke, push, ...), so this
 * classifier never returns them today. A test asserts that reservation.
 */
export function classifyGatewayError(error: unknown): GatewayErrorClass {
  if (!(error instanceof GatewayRpcError)) {
    return "unknown";
  }
  if (error.kind === "rpc") {
    if (typeof error.code === "number") {
      return GATEWAY_RPC_ERROR_CODE_CLASSES[error.code] ?? "unknown";
    }
    return "unknown";
  }
  return GATEWAY_TRANSPORT_KIND_CLASSES[error.kind];
}
