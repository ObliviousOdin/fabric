import { afterEach, describe, expect, it, vi } from "vitest";

import { api, setManagementProfile } from "./api";

const SESSION_HEADER = "X-Fabric-Session-Token";

afterEach(() => {
  setManagementProfile("");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function jsonFetchMock(body: unknown = { ok: true }) {
  return vi.fn<typeof fetch>(
    async () =>
      new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
  );
}

describe("api.getStatus", () => {
  it("coalesces concurrent shell and Home reads for the same profile", async () => {
    vi.stubGlobal("window", {});
    let resolveFetch: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const shellRequest = api.getStatus();
    const homeRequest = api.getStatus();

    expect(homeRequest).toBe(shellRequest);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveFetch?.(
      new Response(JSON.stringify({ active_sessions: 0 }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    await Promise.all([shellRequest, homeRequest]);
  });

  it("never coalesces status reads across machine profiles", async () => {
    vi.stubGlobal("window", {});
    const fetchMock = jsonFetchMock({ active_sessions: 0 });
    vi.stubGlobal("fetch", fetchMock);

    setManagementProfile("operator-a");
    const first = api.getStatus();
    setManagementProfile("operator-b");
    const second = api.getStatus();
    await Promise.all([first, second]);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/status?profile=operator-a",
      "/api/status?profile=operator-b",
    ]);
  });
});

describe("api.getModelOptions", () => {
  it("requests a live model refresh when asked", async () => {
    vi.stubGlobal("window", {});

    const fetchMock = jsonFetchMock({ providers: [] });
    vi.stubGlobal("fetch", fetchMock);

    await api.getModelOptions({ refresh: true });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/model/options?refresh=1&include_unconfigured=1",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("keeps explicit profile scoping when refreshing", async () => {
    vi.stubGlobal("window", {});

    const fetchMock = jsonFetchMock({ providers: [] });
    vi.stubGlobal("fetch", fetchMock);

    await api.getModelOptions({ profile: "default", refresh: true });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/model/options?profile=default&refresh=1&include_unconfigured=1",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});

describe("api OAuth helpers", () => {
  it("scopes every OAuth read and mutation to the selected management profile", async () => {
    vi.stubGlobal("window", {});
    const fetchMock = jsonFetchMock({ ok: true, providers: [] });
    vi.stubGlobal("fetch", fetchMock);
    setManagementProfile("coder team");

    await api.getOAuthProviders();
    await api.disconnectOAuthProvider("anthropic");
    await api.startOAuthLogin("openai-codex");
    await api.submitOAuthCode("anthropic", "oauth-session", "code-123");
    await api.pollOAuthSession("openai-codex", "oauth-session");
    await api.cancelOAuthSession("openai-codex", "oauth-session");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/providers/oauth?profile=coder%20team",
      "/api/providers/oauth/anthropic?profile=coder%20team",
      "/api/providers/oauth/openai-codex/start?profile=coder%20team",
      "/api/providers/oauth/anthropic/submit?profile=coder%20team",
      "/api/providers/oauth/openai-codex/poll/oauth-session?profile=coder%20team",
      "/api/providers/oauth/openai-codex/sessions/oauth-session?profile=coder%20team",
    ]);
  });

  it("starts OAuth login in gated mode without requiring an injected session token", async () => {
    vi.stubGlobal("window", { __HERMES_AUTH_REQUIRED__: true });
    const fetchMock = jsonFetchMock({
      flow: "device_code",
      session_id: "oauth-session",
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.startOAuthLogin("openai-codex");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/providers/oauth/openai-codex/start?profile=current",
      expect.objectContaining({
        body: "{}",
        credentials: "include",
        method: "POST",
      }),
    );
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.has(SESSION_HEADER)).toBe(false);
  });

  it("sends a caller-pinned account revision for an ownership-choice start", async () => {
    vi.stubGlobal("window", {});
    const fetchMock = jsonFetchMock({
      flow: "device_code",
      session_id: "oauth-session",
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.startOAuthLogin("openai-codex", "origin-profile", {
      expectedRevision: 7,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/providers/oauth/openai-codex/start?profile=origin-profile",
      expect.objectContaining({
        body: '{"expected_revision":7}',
        method: "POST",
      }),
    );
  });

  it("still sends the injected session token for OAuth login in loopback mode", async () => {
    vi.stubGlobal("window", { __HERMES_SESSION_TOKEN__: "loopback-token" });
    const fetchMock = jsonFetchMock({
      flow: "device_code",
      session_id: "oauth-session",
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.startOAuthLogin("openai-codex");

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get(SESSION_HEADER)).toBe("loopback-token");
  });

  it("runs provider auth mutations in gated mode via cookie auth", async () => {
    vi.stubGlobal("window", { __HERMES_AUTH_REQUIRED__: true });
    const fetchMock = jsonFetchMock({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    await api.disconnectOAuthProvider("anthropic");
    await api.submitOAuthCode("anthropic", "oauth-session", "code-123");
    await api.cancelOAuthSession("anthropic", "oauth-session");
    await api.revealEnvVar("OPENAI_API_KEY");

    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit;
      expect(init.credentials).toBe("include");
      expect((init.headers as Headers).has(SESSION_HEADER)).toBe(false);
    }
  });
});

describe("api provider-account helpers", () => {
  it("pins reads and managed-request mutations to an explicit profile", async () => {
    vi.stubGlobal("window", {});
    const fetchMock = jsonFetchMock({
      created: null,
      request: null,
      snapshot: { revision: 0 },
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.getProviderAccount("openai-codex", "origin profile");
    await api.createProviderManagedRequest(
      "openai-codex",
      "front desk",
      0,
      "origin profile",
    );
    await api.recordProviderAccountHandoff(
      "openai-codex",
      "par_0123456789abcdef01234567",
      1,
      "origin profile",
    );

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/providers/accounts/openai-codex?profile=origin%20profile",
      "/api/providers/accounts/openai-codex/managed-request?profile=origin%20profile",
      "/api/providers/accounts/openai-codex/handoff-attempted?profile=origin%20profile",
    ]);
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({
        body: JSON.stringify({
          device_label: "front desk",
          expected_revision: 0,
        }),
        method: "POST",
      }),
    );
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({
      expected_revision: 1,
      request_id: "par_0123456789abcdef01234567",
    });
  });
});

describe("memory profile scoping", () => {
  it("scopes memory status, provider hub, and provider selection together", async () => {
    vi.stubGlobal("window", {});
    const fetchMock = jsonFetchMock({ ok: true, providers: [] });
    vi.stubGlobal("fetch", fetchMock);
    setManagementProfile("research team");

    await api.getMemory();
    await api.getPluginsHub();
    await api.savePluginProviders({ memory_provider: "holographic" });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/memory?profile=research%20team",
      "/api/dashboard/plugins/hub?profile=research%20team",
      "/api/dashboard/plugin-providers?profile=research%20team",
    ]);
  });
});
