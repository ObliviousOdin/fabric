import type { RemoteGatewayConnection } from "@fabric/shared";

interface LegacyBrowserPairingPayload {
  connection: RemoteGatewayConnection;
  kind: "legacy";
  pairingUri: string;
}

export interface BrowserEnrollmentPairingPayload {
  auth: "browser" | "local";
  baseUrl: string;
  enrollment: string;
  kind: "enrollment";
  pairingUri: string;
}

export type BrowserPairingPayload =
  | BrowserEnrollmentPairingPayload
  | LegacyBrowserPairingPayload;

const enrollmentHandlePattern = /^[A-Za-z0-9_-]{43,128}$/;

function exactParams(params: URLSearchParams, keys: readonly string[]): boolean {
  const entries = [...params.entries()];
  return (
    entries.length === keys.length &&
    new Set(entries.map(([key]) => key)).size === entries.length &&
    entries.every(([key]) => keys.includes(key))
  );
}

function parsePairingGateway(raw: string, requireHttps: boolean): URL | null {
  try {
    // `URL` helpfully trims surrounding whitespace. Machine-issued v2 pairing
    // grammar must be literal so a scanner cannot make a different decision
    // than the native clients.
    if (requireHttps && (raw.trim() !== raw || /[\u0000-\u0020]/u.test(raw))) {
      return null;
    }
    const gateway = new URL(raw);
    if (
      (gateway.protocol !== "http:" && gateway.protocol !== "https:") ||
      (requireHttps && gateway.protocol !== "https:") ||
      !gateway.hostname ||
      gateway.username ||
      gateway.password ||
      gateway.pathname !== "/" ||
      gateway.search ||
      gateway.hash
    ) {
      return null;
    }
    return gateway;
  } catch {
    return null;
  }
}

export function parsePairingPayloadHash(
  hash: string,
): BrowserPairingPayload | null {
  const fragment = hash.startsWith("#") ? hash.slice(1) : hash;
  const outer = new URLSearchParams(fragment);
  if (!exactParams(outer, ["pair"])) {
    return null;
  }
  const pairing = outer.get("pair");
  if (!pairing) {
    return null;
  }

  try {
    const uri = new URL(pairing);
    if (
      uri.protocol !== "fabric:" ||
      uri.hostname !== "pair" ||
      uri.username ||
      uri.password ||
      uri.port ||
      uri.pathname !== "" ||
      uri.hash
    ) {
      return null;
    }
    const version = uri.searchParams.get("v");
    const auth = uri.searchParams.get("auth");

    if (version === "2") {
      if (
        !exactParams(uri.searchParams, ["v", "url", "enrollment", "auth"]) ||
        (auth !== "browser" && auth !== "local")
      ) {
        return null;
      }
      const gateway = parsePairingGateway(uri.searchParams.get("url") || "", true);
      const enrollment = uri.searchParams.get("enrollment") || "";
      if (!gateway || !enrollmentHandlePattern.test(enrollment)) {
        return null;
      }
      return {
        auth,
        baseUrl: gateway.toString(),
        enrollment,
        kind: "enrollment",
        pairingUri: pairing,
      };
    }

    if (version !== "1" || (auth !== "gated" && auth !== "token")) {
      return null;
    }
    const gateway = parsePairingGateway(uri.searchParams.get("url") || "", false);
    if (!gateway) {
      return null;
    }
    const token = uri.searchParams.get("token") || "";
    if (
      !exactParams(
        uri.searchParams,
        auth === "token" ? ["v", "url", "auth", "token"] : ["v", "url", "auth"],
      ) ||
      (auth === "token" && !token)
    ) {
      return null;
    }
    return {
      connection:
        auth === "token"
          ? { authMode: "token", baseUrl: gateway.toString(), token }
          : { authMode: "cookie", baseUrl: gateway.toString() },
      kind: "legacy",
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
