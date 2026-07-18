import { buildFabricWebSocketUrl } from "./websocket-url";

export interface RemoteGatewayStatus {
  active_sessions?: number;
  auth_providers?: string[];
  auth_required?: boolean;
  version?: string;
}

export interface RemoteAuthProvider {
  display_name: string;
  name: string;
  requires_totp: boolean;
  supports_password: boolean;
}

export interface RemoteAuthProvidersResponse {
  providers: RemoteAuthProvider[];
}

export interface RemoteGatewayConnection {
  authMode: "cookie" | "token";
  baseUrl: string;
  token?: string;
}

export interface PasswordLoginInput {
  otp?: string;
  password: string;
  provider: string;
  username: string;
}

export interface RemoteGatewayFetchOptions {
  fetch?: typeof globalThis.fetch;
  signal?: AbortSignal;
}

export class RemoteGatewayHttpError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "RemoteGatewayHttpError";
    this.status = status;
  }
}

function fetchImpl(options: RemoteGatewayFetchOptions): typeof globalThis.fetch {
  const implementation = options.fetch ?? globalThis.fetch;
  if (!implementation) {
    throw new Error("fetch is unavailable in this runtime");
  }
  return implementation;
}

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown };
    const detail = body.detail ?? body.message;
    return typeof detail === "string" && detail.trim() ? detail : fallback;
  } catch {
    return fallback;
  }
}

export function normalizeRemoteGatewayBaseUrl(value: string): string {
  const raw = value.trim();
  if (!raw) {
    if (typeof window === "undefined") {
      throw new Error("A gateway URL is required outside a browser");
    }
    return window.location.origin;
  }

  const withProtocol = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
  const url = new URL(withProtocol);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("Gateway URL must use http:// or https://");
  }
  url.hash = "";
  url.search = "";
  url.pathname = url.pathname.replace(/\/+$/, "");
  return url.toString().replace(/\/$/, "");
}

export function remoteGatewayHttpUrl(baseUrl: string, path: string): string {
  const base = new URL(normalizeRemoteGatewayBaseUrl(baseUrl));
  const basePath = base.pathname.replace(/\/+$/, "");
  const endpoint = path.startsWith("/") ? path : `/${path}`;
  base.pathname = `${basePath}${endpoint}`.replace(/\/{2,}/g, "/");
  base.search = "";
  base.hash = "";
  return base.toString();
}

export async function fetchRemoteGatewayStatus(
  baseUrl: string,
  options: RemoteGatewayFetchOptions = {},
): Promise<RemoteGatewayStatus> {
  const response = await fetchImpl(options)(
    remoteGatewayHttpUrl(baseUrl, "/api/status"),
    {
      credentials: "include",
      signal: options.signal,
    },
  );
  if (!response.ok) {
    throw new RemoteGatewayHttpError(
      await readError(response, `Gateway status failed: HTTP ${response.status}`),
      response.status,
    );
  }
  return (await response.json()) as RemoteGatewayStatus;
}

export async function fetchRemoteAuthProviders(
  baseUrl: string,
  options: RemoteGatewayFetchOptions = {},
): Promise<RemoteAuthProvider[]> {
  const response = await fetchImpl(options)(
    remoteGatewayHttpUrl(baseUrl, "/api/auth/providers"),
    {
      credentials: "include",
      signal: options.signal,
    },
  );
  if (!response.ok) {
    throw new RemoteGatewayHttpError(
      await readError(response, `Provider discovery failed: HTTP ${response.status}`),
      response.status,
    );
  }
  const body = (await response.json()) as RemoteAuthProvidersResponse;
  return Array.isArray(body.providers) ? body.providers : [];
}

export async function loginRemoteGatewayWithPassword(
  baseUrl: string,
  input: PasswordLoginInput,
  options: RemoteGatewayFetchOptions = {},
): Promise<void> {
  const response = await fetchImpl(options)(
    remoteGatewayHttpUrl(baseUrl, "/auth/password-login"),
    {
      body: JSON.stringify({
        next: "/",
        otp: input.otp?.trim() ?? "",
        password: input.password,
        provider: input.provider,
        username: input.username,
      }),
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      method: "POST",
      signal: options.signal,
    },
  );
  if (!response.ok) {
    throw new RemoteGatewayHttpError(
      await readError(response, `Sign-in failed: HTTP ${response.status}`),
      response.status,
    );
  }
}

export async function mintRemoteGatewayTicket(
  baseUrl: string,
  options: RemoteGatewayFetchOptions = {},
): Promise<string> {
  const response = await fetchImpl(options)(
    remoteGatewayHttpUrl(baseUrl, "/api/auth/ws-ticket"),
    {
      credentials: "include",
      method: "POST",
      signal: options.signal,
    },
  );
  if (!response.ok) {
    throw new RemoteGatewayHttpError(
      await readError(response, `Session refresh failed: HTTP ${response.status}`),
      response.status,
    );
  }
  const body = (await response.json()) as { ticket?: unknown };
  if (typeof body.ticket !== "string" || !body.ticket) {
    throw new Error("Gateway returned an invalid WebSocket ticket");
  }
  return body.ticket;
}

export function buildRemoteGatewayWebSocketUrl(
  baseUrl: string,
  authParam: readonly [string, string],
): string {
  const base = new URL(normalizeRemoteGatewayBaseUrl(baseUrl));
  return buildFabricWebSocketUrl({
    authParam,
    basePath: base.pathname,
    host: base.host,
    path: "/api/ws",
    protocol: base.protocol,
  });
}

export async function resolveRemoteGatewayWebSocketUrl(
  connection: RemoteGatewayConnection,
  options: RemoteGatewayFetchOptions = {},
): Promise<string> {
  if (connection.authMode === "token") {
    if (!connection.token) {
      throw new Error("A session token is required for token authentication");
    }
    return buildRemoteGatewayWebSocketUrl(connection.baseUrl, [
      "token",
      connection.token,
    ]);
  }

  const ticket = await mintRemoteGatewayTicket(connection.baseUrl, options);
  return buildRemoteGatewayWebSocketUrl(connection.baseUrl, ["ticket", ticket]);
}
