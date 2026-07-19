import type { RemoteGatewayConnection } from "@fabric/shared";

export interface BrowserPairingPayload {
  connection: RemoteGatewayConnection;
  pairingUri: string;
}

export function parsePairingPayloadHash(hash: string): BrowserPairingPayload | null {
  const fragment = hash.startsWith("#") ? hash.slice(1) : hash;
  const pairing = new URLSearchParams(fragment).get("pair");
  if (!pairing) {
    return null;
  }

  try {
    const uri = new URL(pairing);
    if (
      uri.protocol !== "fabric:" ||
      uri.hostname !== "pair" ||
      uri.searchParams.get("v") !== "1"
    ) {
      return null;
    }
    const gateway = new URL(uri.searchParams.get("url") || "");
    if (
      (gateway.protocol !== "http:" && gateway.protocol !== "https:") ||
      !gateway.hostname ||
      gateway.username ||
      gateway.password ||
      gateway.search ||
      gateway.hash
    ) {
      return null;
    }
    const auth = uri.searchParams.get("auth");
    const token = uri.searchParams.get("token") || "";
    if (auth !== "gated" && auth !== "token") {
      return null;
    }
    if ((auth === "token" && !token) || (auth === "gated" && token)) {
      return null;
    }
    return {
      connection:
        auth === "token"
          ? { authMode: "token", baseUrl: gateway.toString(), token }
          : { authMode: "cookie", baseUrl: gateway.toString() },
      pairingUri: pairing,
    };
  } catch {
    return null;
  }
}

export function parsePairingHash(hash: string): string | null {
  return parsePairingPayloadHash(hash)?.pairingUri ?? null;
}

export function takePairingPayload(): BrowserPairingPayload | null {
  const pairing = parsePairingPayloadHash(window.location.hash);
  if (window.location.hash) {
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
  }
  return pairing;
}
