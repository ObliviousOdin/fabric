import { describe, expect, it, vi } from "vitest";

import {
  buildRemoteGatewayWebSocketUrl,
  fetchRemoteAuthProviders,
  hasRemoteGatewaySession,
  loginRemoteGatewayWithPassword,
  normalizeRemoteGatewayBaseUrl,
  remoteGatewayHttpUrl,
  resolveRemoteGatewayWebSocketUrl,
} from "./remote-gateway";

describe("remote gateway URLs", () => {
  it("normalizes host input and preserves a reverse-proxy base path", () => {
    expect(normalizeRemoteGatewayBaseUrl("fabric.local:8080/root/")).toBe(
      "http://fabric.local:8080/root",
    );
    expect(
      remoteGatewayHttpUrl("https://fabric.example/root", "/api/status"),
    ).toBe("https://fabric.example/root/api/status");
    expect(
      buildRemoteGatewayWebSocketUrl("https://fabric.example/root", [
        "ticket",
        "one two",
      ]),
    ).toBe("wss://fabric.example/root/api/ws?ticket=one+two");
  });

  it("requires a token instead of opening an unauthenticated token socket", async () => {
    await expect(
      resolveRemoteGatewayWebSocketUrl({
        authMode: "token",
        baseUrl: "https://fabric.example",
      }),
    ).rejects.toThrow("session token is required");
  });
});

describe("remote gateway auth", () => {
  it("distinguishes a valid cookie session from an unauthenticated response", async () => {
    const authenticatedFetch = vi.fn(
      async () => new Response('{"user_id":"oauth-user"}', { status: 200 }),
    );
    const unauthenticatedFetch = vi.fn(
      async () => new Response('{"detail":"Unauthorized"}', { status: 401 }),
    );

    await expect(
      hasRemoteGatewaySession("https://fabric.example", {
        fetch: authenticatedFetch,
      }),
    ).resolves.toBe(true);
    await expect(
      hasRemoteGatewaySession("https://fabric.example", {
        fetch: unauthenticatedFetch,
      }),
    ).resolves.toBe(false);
    expect(authenticatedFetch).toHaveBeenCalledWith(
      "https://fabric.example/api/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("discovers password and TOTP capabilities", async () => {
    const fetch = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            providers: [
              {
                display_name: "Fabric Password",
                name: "password",
                requires_totp: true,
                supports_password: true,
              },
            ],
          }),
          { status: 200 },
        ),
    );

    await expect(
      fetchRemoteAuthProviders("https://fabric.example", { fetch }),
    ).resolves.toEqual([
      {
        display_name: "Fabric Password",
        name: "password",
        requires_totp: true,
        supports_password: true,
      },
    ]);
  });

  it("posts credentials without persisting them in client state", async () => {
    const fetch = vi.fn(
      async () => new Response('{"ok":true}', { status: 200 }),
    );

    await loginRemoteGatewayWithPassword(
      "https://fabric.example",
      {
        otp: "123456",
        password: "secret",
        provider: "password",
        username: "channa",
      },
      { fetch },
    );

    expect(fetch).toHaveBeenCalledWith(
      "https://fabric.example/auth/password-login",
      expect.objectContaining({
        body: JSON.stringify({
          next: "/",
          otp: "123456",
          password: "secret",
          provider: "password",
          username: "channa",
        }),
        credentials: "include",
        method: "POST",
      }),
    );
  });
});
