import { describe, expect, it, vi } from "vitest";

import {
  createCookieAutoConnectClaim,
  probeMobileGatewayAuth,
} from "./probe-auth";

describe("mobile gateway auth probe", () => {
  it("allows only one automatic cookie connection per page load", () => {
    const claim = createCookieAutoConnectClaim();

    expect(claim()).toBe(true);
    expect(claim()).toBe(false);
    expect(claim()).toBe(false);
  });

  it("connects with the cookie created by a completed OAuth return", async () => {
    const fetch = vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input)).pathname;
      if (path === "/api/status") {
        return new Response('{"auth_required":true}', { status: 200 });
      }
      if (path === "/api/auth/me") {
        return new Response('{"user_id":"oauth-user"}', { status: 200 });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    await expect(
      probeMobileGatewayAuth("https://fabric.example", { fetch }),
    ).resolves.toEqual({
      authMode: "cookie",
      connection: {
        authMode: "cookie",
        baseUrl: "https://fabric.example",
      },
      providers: [],
    });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("discovers sign-in providers when no cookie session exists", async () => {
    const provider = {
      display_name: "Portal",
      name: "portal",
      requires_totp: false,
      supports_password: false,
    };
    const fetch = vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input)).pathname;
      if (path === "/api/status") {
        return new Response('{"auth_required":true}', { status: 200 });
      }
      if (path === "/api/auth/me") {
        return new Response('{"detail":"Unauthorized"}', { status: 401 });
      }
      if (path === "/api/auth/providers") {
        return new Response(JSON.stringify({ providers: [provider] }), {
          status: 200,
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    await expect(
      probeMobileGatewayAuth("https://fabric.example", { fetch }),
    ).resolves.toEqual({
      authMode: "cookie",
      connection: null,
      providers: [provider],
    });
  });
});
