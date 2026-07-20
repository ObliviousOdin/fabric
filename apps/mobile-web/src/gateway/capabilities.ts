import {
  negotiateGatewayCapabilities,
  supportsGatewayMethod,
  type GatewayCapabilityClient,
  type GatewayCompatibility,
} from "@fabric/shared";

export type MobileGatewayCapabilityState =
  | GatewayCompatibility
  | { kind: "negotiating" }
  | null;

interface NegotiateMobileGatewayOptions {
  client: GatewayCapabilityClient;
  isCurrent: () => boolean;
  publish: (compatibility: GatewayCompatibility) => void;
  refreshSessions: () => Promise<void>;
}

/**
 * Finish an authenticated mobile connection in the only safe order:
 * negotiate, reject stale results, publish compatibility, then list sessions.
 */
export async function negotiateMobileGatewayConnection({
  client,
  isCurrent,
  publish,
  refreshSessions,
}: NegotiateMobileGatewayOptions): Promise<GatewayCompatibility | null> {
  const compatibility = await negotiateGatewayCapabilities(client);
  if (!isCurrent()) {
    return null;
  }

  publish(compatibility);
  if (!mobileGatewaySupports(compatibility, "session.list") || !isCurrent()) {
    return compatibility;
  }

  await refreshSessions();
  return isCurrent() ? compatibility : null;
}

export function mobileGatewaySupports(
  state: MobileGatewayCapabilityState,
  method: string,
): boolean {
  return Boolean(
    state &&
    state.kind !== "negotiating" &&
    supportsGatewayMethod(state, method),
  );
}

export function capabilityUnavailableMessage(
  state: MobileGatewayCapabilityState,
  method: string,
): string {
  if (!state) {
    return "Connect to a Fabric gateway first.";
  }
  if (state.kind === "negotiating") {
    return "Checking gateway compatibility. Try again in a moment.";
  }
  if (state.kind === "incompatible") {
    return `This gateway requires mobile contract ${state.minimum}. Update Fabric mobile before changing sessions.`;
  }
  if (state.kind === "invalid") {
    return "The gateway returned an invalid capability contract. Reconnect after updating Fabric.";
  }
  return `${method} is not available on this gateway. Update Fabric to use this control.`;
}
