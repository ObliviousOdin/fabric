import {
  fetchRemoteAuthProviders,
  fetchRemoteGatewayStatus,
  hasRemoteGatewaySession,
  type RemoteAuthProvider,
  type RemoteGatewayConnection,
  type RemoteGatewayFetchOptions,
} from "@fabric/shared";

export interface MobileGatewayAuthProbe {
  authMode: RemoteGatewayConnection["authMode"];
  connection: RemoteGatewayConnection | null;
  providers: RemoteAuthProvider[];
}

export function createCookieAutoConnectClaim(): () => boolean {
  let claimed = false;
  return () => {
    if (claimed) {
      return false;
    }
    claimed = true;
    return true;
  };
}

export async function probeMobileGatewayAuth(
  baseUrl: string,
  options: RemoteGatewayFetchOptions = {},
): Promise<MobileGatewayAuthProbe> {
  const status = await fetchRemoteGatewayStatus(baseUrl, options);
  if (!status.auth_required) {
    return { authMode: "token", connection: null, providers: [] };
  }

  if (await hasRemoteGatewaySession(baseUrl, options)) {
    return {
      authMode: "cookie",
      connection: { authMode: "cookie", baseUrl },
      providers: [],
    };
  }

  return {
    authMode: "cookie",
    connection: null,
    providers: await fetchRemoteAuthProviders(baseUrl, options),
  };
}
