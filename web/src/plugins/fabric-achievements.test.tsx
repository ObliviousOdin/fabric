// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  exposePluginSDK,
  getPluginComponent,
} from "./registry";

vi.mock("@/i18n", () => ({
  useI18n: () => ({ t: { achievements: null }, locale: "en" }),
}));

const bundle = readFileSync(
  resolve(
    process.cwd(),
    "../plugins/fabric-achievements/dashboard/dist/index.js",
  ),
  "utf8",
);

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

async function flushEffects() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function leaderboardInvite(overrides: Record<string, unknown> = {}) {
  const payload = {
    v: 1,
    relay: "http://relay-host.example.ts.net:9137",
    team_id: "team-1",
    team_name: "Fabric Crew",
    secret: "join-secret-that-must-stay-private",
    ...overrides,
  };
  return `fbl1_${window.btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}`;
}

describe("fabric-achievements leaderboard bundle", () => {
  let container: HTMLDivElement;
  let root: Root;
  let fetchJSON: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    fetchJSON = vi.fn((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      return Promise.resolve({ ok: true });
    });

    exposePluginSDK();
    const sdk = window.__HERMES_PLUGIN_SDK__ as unknown as {
      fetchJSON: typeof fetchJSON;
    };
    sdk.fetchJSON = fetchJSON;
    window.eval(bundle);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
    vi.restoreAllMocks();
  });

  async function renderLeaderboard() {
    const Plugin = getPluginComponent("fabric-achievements");
    expect(Plugin).toBeDefined();
    await act(async () => root.render(Plugin ? <Plugin /> : null));
    const leaderboardButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Leaderboard",
    );
    expect(leaderboardButton).toBeDefined();
    await act(async () => leaderboardButton?.click());
    await flushEffects();
  }

  it("decodes a safe invite preview locally, masks the secret, and gates join on preflight", async () => {
    const preflight = deferred<Record<string, unknown>>();
    const invite = leaderboardInvite();
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({ ok: true, membership: null });
      }
      if (url.endsWith("/team/preflight")) return preflight.promise;
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const input = container.querySelector<HTMLInputElement>('input[placeholder="fbl1_…"]');
    const join = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Join and share my score",
    );
    const inviteLabel = container.querySelector<HTMLLabelElement>("label[for]");
    const revealButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Reveal",
    );
    expect(input?.type).toBe("password");
    expect(inviteLabel?.htmlFor).toBe(input?.id);
    expect(inviteLabel?.contains(revealButton || null)).toBe(false);
    expect(join?.disabled).toBe(true);

    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (input) {
        setValue?.call(input, invite);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    expect(container.textContent).toContain("Fabric Crew");
    expect(container.textContent).toContain("relay-host.example.ts.net:9137");
    expect(join?.disabled).toBe(true);
    expect(fetchJSON).toHaveBeenCalledWith(
      "/api/plugins/fabric-achievements/team/preflight",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ invite_code: invite }),
      }),
    );

    await act(async () => {
      preflight.resolve({
        state: "CONNECTED",
        title: "Relay ready",
        message: "Fabric verified the relay and invite.",
        actor: "member",
        retryable: false,
        can_join: true,
        can_restart: false,
        preview: {
          team_name: "Fabric Crew",
          relay_host: "relay-host.example.ts.net",
          relay_port: 9137,
        },
        checks: [{ name: "credentials", status: "ok" }],
        diagnostic: { state: "CONNECTED" },
      });
      await preflight.promise;
    });

    expect(join?.disabled).toBe(false);
    const reveal = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Reveal",
    );
    await act(async () => reveal?.click());
    expect(input?.type).toBe("text");

    const rotatedInvite = leaderboardInvite({
      team_id: "team-2",
      secret: "rotated-secret-that-must-stay-private",
    });
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (input) {
        setValue?.call(input, rotatedInvite);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    expect(input?.type).toBe("password");
    await flushEffects();
    expect(join?.disabled).toBe(false);
    await act(async () => {
      input?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    await flushEffects();
    expect(fetchJSON).toHaveBeenCalledWith(
      "/api/plugins/fabric-achievements/team/join",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          invite_code: rotatedInvite,
          display_name: "",
          publish_opt_in: true,
        }),
      }),
    );
  });

  it("redacts an invite secret embedded in the locally decoded team preview", async () => {
    const secret = "preview-secret-that-must-not-render";
    const invite = leaderboardInvite({
      secret,
      team_name: `Crew ${secret} HQ`,
    });
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) return Promise.resolve({ ok: true, membership: null });
      if (url.endsWith("/team/preflight")) return new Promise(() => {});
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const input = container.querySelector<HTMLInputElement>('input[placeholder="fbl1_…"]');
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (input) {
        setValue?.call(input, invite);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    expect(container.textContent).toContain("Team");
    expect(container.textContent).not.toContain(secret);
  });

  it.each([
    ["non-string credentials", { secret: 46 }],
    ["an unsupported version", { v: 2 }],
  ])("rejects a locally decoded invite with %s", async (_case, overrides) => {
    const malformedInvite = leaderboardInvite(overrides);
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({ ok: true, membership: null });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const input = container.querySelector<HTMLInputElement>('input[placeholder="fbl1_…"]');
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (input) {
        setValue?.call(input, malformedInvite);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    await flushEffects();

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "This does not look like a valid Fabric leaderboard invite.",
    );
    expect(
      fetchJSON.mock.calls.some(([url]) => String(url).endsWith("/team/preflight")),
    ).toBe(false);
  });

  it("shows relay-specific member recovery, retries in place, and copies only safe diagnostics", async () => {
    const invite = leaderboardInvite();
    const clipboardWrite = vi.fn((text: string) => {
      void text;
      return Promise.resolve();
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });
    let preflightCalls = 0;
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) return Promise.resolve({ ok: true, membership: null });
      if (url.endsWith("/team/preflight")) {
        preflightCalls += 1;
        return Promise.resolve(preflightCalls === 1 ? {
          state: "HOST_REACHABLE_RELAY_DOWN",
          title: "Relay service is not responding",
          message: "The relay host is online, but its Fabric leaderboard relay is not responding on port 9137. Your Tailscale connection is working. Ask the team owner to restart the Fabric leaderboard relay.",
          actor: "member",
          retryable: true,
          can_join: false,
          can_restart: false,
          preview: { team_name: "Fabric Crew", relay_host: "relay-host.example.ts.net", relay_port: 9137 },
          checks: [
            { name: "Tailscale host", status: "ok" },
            { name: "Relay health", status: "failed" },
          ],
          diagnostic: {
            state: "HOST_REACHABLE_RELAY_DOWN",
            invite_code: invite,
            member_token: "private-member-token",
            transcript: "private transcript",
            raw_metrics: { score: 9000 },
          },
        } : {
          state: "CONNECTED",
          title: "Relay ready",
          message: "Fabric verified the relay and invite.",
          actor: "member",
          retryable: false,
          can_join: true,
          can_restart: false,
          preview: { team_name: "Fabric Crew", relay_host: "relay-host.example.ts.net", relay_port: 9137 },
          checks: [{ name: "credentials", status: "ok" }],
          diagnostic: { state: "CONNECTED" },
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const input = container.querySelector<HTMLInputElement>('input[placeholder="fbl1_…"]');
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (input) {
        setValue?.call(input, invite);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    await flushEffects();

    expect(container.textContent).toContain("The relay host is online");
    expect(container.textContent).toContain("Your Tailscale connection is working");
    expect(container.textContent).toContain("member action");
    expect(container.textContent).not.toContain("Restart relay");

    const copy = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Copy diagnostic",
    );
    await act(async () => copy?.click());
    await flushEffects();
    const copied = String(clipboardWrite.mock.calls[0]?.[0]);
    expect(copied).toContain("HOST_REACHABLE_RELAY_DOWN");
    expect(copied).toContain("relay-host.example.ts.net");
    expect(copied).not.toContain("fbl1_");
    expect(copied).not.toContain("private-member-token");
    expect(copied).not.toContain("private transcript");
    expect(copied).not.toContain("raw_metrics");

    const retry = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Retry",
    );
    await act(async () => retry?.click());
    await flushEffects();
    expect(preflightCalls).toBe(2);
    expect(container.textContent).toContain("Relay ready");
    const join = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Join and share my score",
    );
    expect(join?.disabled).toBe(false);
    expect(document.activeElement).toBe(join);
  });

  it("replaces a stale successful preflight when the join request returns a newer connection failure", async () => {
    const invite = leaderboardInvite();
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) return Promise.resolve({ ok: true, membership: null });
      if (url.endsWith("/team/preflight")) {
        return Promise.resolve({
          state: "CONNECTED",
          title: "Relay ready",
          message: "Fabric verified the relay and invite.",
          actor: "member",
          retryable: false,
          can_join: true,
          can_restart: false,
          checks: [{ name: "credentials", status: "pass" }],
          diagnostic: { state: "CONNECTED" },
        });
      }
      if (url.endsWith("/team/join")) {
        return Promise.resolve({
          ok: false,
          connection: {
            state: "HOST_REACHABLE_RELAY_DOWN",
            title: "Leaderboard relay stopped responding",
            message: "The host is online, but the relay stopped responding before Fabric could join.",
            actor: "member",
            retryable: true,
            can_join: false,
            can_restart: false,
            checks: [{ name: "health", status: "fail" }],
            diagnostic: { state: "HOST_REACHABLE_RELAY_DOWN" },
          },
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const input = container.querySelector<HTMLInputElement>('input[placeholder="fbl1_…"]');
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (input) {
        setValue?.call(input, invite);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    await flushEffects();

    const join = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Join and share my score",
    );
    expect(join?.disabled).toBe(false);
    await act(async () => join?.click());
    await flushEffects();

    expect(container.textContent).toContain("Leaderboard relay stopped responding");
    expect(container.textContent).toContain("stopped responding before Fabric could join");
    expect(join?.disabled).toBe(true);
  });

  it("surfaces a business failure even when the join response also carries a connected diagnostic", async () => {
    const invite = leaderboardInvite();
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) return Promise.resolve({ ok: true, membership: null });
      if (url.endsWith("/team/preflight")) {
        return Promise.resolve({
          state: "CONNECTED",
          title: "Relay ready",
          message: "Fabric verified the relay and invite.",
          actor: "member",
          retryable: false,
          can_join: true,
          can_restart: false,
          checks: [{ name: "credentials", status: "pass" }],
          diagnostic: { state: "CONNECTED" },
        });
      }
      if (url.endsWith("/team/join")) {
        return Promise.resolve({
          ok: false,
          error: "This team is full.",
          connection: {
            state: "CONNECTED",
            title: "Relay ready",
            message: "Fabric verified the relay and invite.",
            actor: "member",
            retryable: false,
            can_join: true,
            can_restart: false,
            checks: [{ name: "credentials", status: "pass" }],
            diagnostic: { state: "CONNECTED" },
          },
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const input = container.querySelector<HTMLInputElement>('input[placeholder="fbl1_…"]');
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (input) {
        setValue?.call(input, invite);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    await flushEffects();
    const join = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Join and share my score",
    );
    await act(async () => join?.click());
    await flushEffects();

    expect(container.querySelector('[role="alert"]')?.textContent).toContain("This team is full.");
    expect(join?.disabled).toBe(false);
  });

  it("offers verified owner recovery, sanitized logs, host telemetry, and masked saved invites", async () => {
    const invite = leaderboardInvite();
    const rotatedInvite = leaderboardInvite({
      team_id: "team-rotated",
      secret: "rotated-owner-secret-that-must-stay-private",
    });
    let leaderboardCalls = 0;
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        leaderboardCalls += 1;
        const membership = {
          team_name: "Fabric Crew",
          display_name: "Owner",
          role: "owner",
          member_id: "owner-1",
          invite_code: leaderboardCalls === 1 ? invite : rotatedInvite,
        };
        return Promise.resolve(leaderboardCalls === 1 ? {
          ok: false,
          error: "Could not reach relay",
          membership,
          leaderboard: [],
          connection: {
            state: "HOST_REACHABLE_RELAY_DOWN",
            title: "Your relay service is offline",
            message: "This relay host is online, but the leaderboard service needs to be restarted.",
            actor: "owner",
            retryable: true,
            can_join: false,
            can_restart: true,
            preview: { team_name: "Fabric Crew", relay_host: "host.example.ts.net", relay_port: 9137 },
            checks: [{ name: "Relay health", status: "failed" }],
            diagnostic: { state: "HOST_REACHABLE_RELAY_DOWN" },
          },
        } : {
          ok: true,
          membership,
          publish_opt_in: false,
          leaderboard: [],
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({
          ok: true,
          tailscale: { installed: true, running: true, magicdns: "host.example.ts.net" },
          local_relay: { ok: false },
          managed_relay: {
            managed: true,
            running: true,
            healthy: false,
            pid: 123,
            port: 9137,
            uptime_seconds: 3661,
            last_successful_health_at: Math.floor(Date.now() / 1000) - 60,
            bind: "0.0.0.0:9137",
          },
          advertised_magicdns_probe: { ok: false, url: "http://host.example.ts.net:9137" },
          default_port: 9137,
        });
      }
      if (url.endsWith("/team/host/logs")) {
        return Promise.resolve({
          ok: true,
          log: "relay startup complete\ninvite=fbl1_private-secret\nsession_content=private transcript",
        });
      }
      if (url.endsWith("/team/host/restart")) return Promise.resolve({ ok: true });
      if (url.endsWith("/team/preflight")) {
        return Promise.resolve({
          state: "CONNECTED",
          title: "Relay ready",
          message: "Fabric verified the relay.",
          actor: "owner",
          retryable: false,
          can_join: true,
          can_restart: true,
          checks: [{ name: "credentials", status: "ok" }],
          diagnostic: { state: "CONNECTED" },
        });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    expect(container.textContent).toContain("Your relay service is offline");
    expect(container.textContent).toContain("Run diagnostics");
    expect(container.textContent).toContain("Restart relay");
    expect(container.textContent).toContain("View relay logs");
    expect(container.textContent).toContain("Uptime");
    expect(container.textContent).toContain("1h 1m");
    expect(container.textContent).toContain("Last successful health");
    expect(container.textContent).toContain("0.0.0.0:9137");
    expect(container.textContent).toContain("Advertised MagicDNS probe");
    const savedInvite = container.querySelector<HTMLInputElement>(".ha-invite-section input");
    expect(savedInvite?.type).toBe("password");
    const revealSavedInvite = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Reveal",
    );
    await act(async () => revealSavedInvite?.click());
    expect(savedInvite?.type).toBe("text");

    const logs = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "View relay logs",
    );
    await act(async () => logs?.click());
    await flushEffects();
    const logText = container.querySelector(".ha-relay-logs pre")?.textContent || "";
    expect(logText).toContain("relay startup complete");
    expect(logText).toContain("[redacted invite]");
    expect(logText).not.toContain("private-secret");
    expect(logText).not.toContain("private transcript");

    const restart = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Restart relay",
    );
    await act(async () => restart?.click());
    await flushEffects();
    expect(fetchJSON.mock.calls.some(([url]) => String(url).endsWith("/team/host/restart"))).toBe(true);
    expect(fetchJSON.mock.calls.some(([url]) => String(url).endsWith("/team/preflight"))).toBe(true);
    expect(savedInvite?.value).toBe(rotatedInvite);
    expect(savedInvite?.type).toBe("password");
    expect(document.activeElement?.tagName).toBe("H1");
  });

  it("keeps a newer refresh authoritative when recovered diagnostics finish with a stale roster", async () => {
    const preflight = deferred<Record<string, unknown>>();
    const staleRoster = deferred<Record<string, unknown>>();
    let leaderboardCalls = 0;
    const membership = {
      team_name: "Original Team",
      display_name: "Owner",
      role: "owner",
      member_id: "owner-1",
    };
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        leaderboardCalls += 1;
        if (leaderboardCalls === 1) {
          return Promise.resolve({
            ok: false,
            error: "Could not reach relay",
            membership,
            leaderboard: [],
            connection: {
              state: "HOST_REACHABLE_RELAY_DOWN",
              title: "Your relay service is offline",
              message: "Restart the relay.",
              actor: "owner",
              retryable: true,
              can_join: false,
              can_restart: true,
              checks: [],
              diagnostic: { state: "HOST_REACHABLE_RELAY_DOWN" },
            },
          });
        }
        if (leaderboardCalls === 2) return staleRoster.promise;
        return Promise.resolve({
          ok: true,
          membership: { ...membership, team_name: "Newest Team" },
          leaderboard: [],
          publish_opt_in: false,
        });
      }
      if (url.endsWith("/team/preflight")) return preflight.promise;
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const diagnostics = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Run diagnostics",
    );
    await act(async () => diagnostics?.click());
    const refresh = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Refresh",
    );
    expect(refresh?.disabled).toBe(true);

    await act(async () => {
      preflight.resolve({
        state: "CONNECTED",
        title: "Relay ready",
        message: "Fabric verified the relay.",
        actor: "owner",
        retryable: false,
        can_join: true,
        can_restart: true,
        checks: [],
        diagnostic: { state: "CONNECTED" },
      });
      await preflight.promise;
    });
    await flushEffects();
    expect(leaderboardCalls).toBe(2);
    expect(refresh?.disabled).toBe(false);

    await act(async () => refresh?.click());
    await flushEffects();
    expect(container.textContent).toContain("Newest Team");

    await act(async () => {
      staleRoster.resolve({
        ok: true,
        membership: { ...membership, team_name: "Stale Team" },
        leaderboard: [],
        publish_opt_in: false,
      });
      await staleRoster.promise;
    });
    await flushEffects();
    expect(container.textContent).toContain("Newest Team");
    expect(container.textContent).not.toContain("Stale Team");
    expect(document.activeElement?.tagName).not.toBe("H1");
  });

  it("keeps relay host controls out of member recovery guidance", async () => {
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({
          ok: false,
          membership: {
            team_name: "Fabric Crew",
            display_name: "Member",
            role: "member",
            member_id: "member-1",
          },
          leaderboard: [],
          connection: {
            state: "HOST_REACHABLE_RELAY_DOWN",
            title: "Relay service is not responding",
            message: "Ask the team owner to restart the Fabric leaderboard relay.",
            actor: "member",
            retryable: true,
            can_join: false,
            can_restart: true,
            checks: [],
            diagnostic: { state: "HOST_REACHABLE_RELAY_DOWN" },
          },
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    expect(container.textContent).toContain("member action");
    expect(container.textContent).toContain("Retry");
    expect(container.textContent).not.toContain("Restart relay");
    expect(container.textContent).not.toContain("View relay logs");
    expect(container.textContent).not.toContain("Run diagnostics");
  });

  it("keeps managed relay controls available after team creation", async () => {
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({
          ok: true,
          membership: {
            team_name: "Fabric Team",
            display_name: "Owner",
            role: "owner",
            member_id: "member-1",
            invite_code: "fbl1_test",
          },
          publish_opt_in: false,
          leaderboard: [],
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({
          ok: true,
          tailscale: { installed: true, running: true, magicdns: "host.ts.net" },
          local_relay: { ok: true },
          managed_relay: {
            managed: true,
            running: true,
            healthy: true,
            pid: 123,
            port: 9137,
          },
          default_port: 9137,
          suggested_relay_url: "http://host.ts.net:9137",
          suggested_is_shareable: true,
          relay_live: true,
        });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();

    expect(container.textContent).toContain("Relay hosting on this machine");
    expect(container.textContent).toContain("PID 123");
    expect(container.textContent).toContain("Stop");
    expect(container.textContent).toContain(
      "If the relay is unavailable, Fabric leaves locally and retries the remote removal.",
    );
  });

  it("surfaces a failed relay action even when status retrieval succeeded", async () => {
    const stoppedStatus = {
      ok: true,
      tailscale: { installed: false, running: false },
      local_relay: { ok: false },
      managed_relay: { managed: false, running: false },
      default_port: 9137,
      suggested_relay_url: null,
      suggested_is_shareable: false,
      relay_live: false,
    };
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({ ok: true, membership: null });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve(stoppedStatus);
      }
      if (url.endsWith("/team/host/start")) {
        return Promise.resolve({
          ...stoppedStatus,
          action_ok: false,
          error: "Relay process identity could not be verified",
        });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    expect(container.textContent).toContain(
      "click Host on this machine to start the small relay here",
    );
    const hostButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Host on this machine",
    );
    expect(hostButton).toBeDefined();
    await act(async () => hostButton?.click());
    await flushEffects();

    expect(container.textContent).toContain(
      "Relay process identity could not be verified",
    );
  });

  it("does not run diagnostics after a managed relay restart is rejected", async () => {
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({
          ok: false,
          membership: {
            team_name: "Fabric Crew",
            display_name: "Owner",
            role: "owner",
            member_id: "owner-1",
          },
          leaderboard: [],
          connection: {
            state: "HOST_REACHABLE_RELAY_DOWN",
            title: "Relay service is offline",
            message: "Restart this managed relay.",
            actor: "owner",
            retryable: true,
            can_join: false,
            can_restart: true,
            checks: [],
            diagnostic: { state: "HOST_REACHABLE_RELAY_DOWN" },
          },
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      if (url.endsWith("/team/host/restart")) {
        return Promise.resolve({
          ok: true,
          action_ok: false,
          error: "Managed relay identity changed before restart",
        });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const restart = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Restart relay",
    );
    await act(async () => restart?.click());
    await flushEffects();

    expect(container.textContent).toContain(
      "Managed relay identity changed before restart",
    );
    expect(
      fetchJSON.mock.calls.some(([url]) => String(url).endsWith("/team/preflight")),
    ).toBe(false);
  });

  it("preserves a manually restored relay URL after auto-fill", async () => {
    const manualRelay = "http://127.0.0.1:9137";
    const otherRelay = "http://127.0.0.1:9237";
    let statusCalls = 0;
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({ ok: true, membership: null });
      }
      if (url.endsWith("/team/host/status")) {
        statusCalls += 1;
        return Promise.resolve({
          ok: true,
          tailscale: { installed: false, running: false },
          local_relay: { ok: statusCalls === 1 },
          managed_relay: { managed: false, running: false },
          default_port: 9137,
          suggested_relay_url: statusCalls === 1 ? manualRelay : null,
          suggested_is_shareable: false,
          relay_live: statusCalls === 1,
        });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const relayInput = container.querySelector<HTMLInputElement>(
      'input[placeholder="http://your-host:9137"]',
    );
    expect(relayInput).not.toBeNull();
    expect(relayInput?.value).toBe(manualRelay);
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      if (relayInput) {
        setValue?.call(relayInput, otherRelay);
        relayInput.dispatchEvent(new Event("input", { bubbles: true }));
        setValue?.call(relayInput, manualRelay);
        relayInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    const detectButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Detect",
    );
    expect(detectButton).toBeDefined();
    await act(async () => detectButton?.click());
    await flushEffects();
    expect(relayInput?.value).toBe(manualRelay);
  });

  it("probes a relay before creating a team and surfaces failure inline", async () => {
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({ ok: true, membership: null });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({
          ok: true,
          tailscale: { installed: false, running: false },
          local_relay: { ok: true },
          managed_relay: { managed: false, running: false },
          default_port: 9137,
          suggested_relay_url: "http://127.0.0.1:9137",
          suggested_is_shareable: false,
          relay_live: true,
        });
      }
      if (url.endsWith("/team/host/probe")) {
        return Promise.resolve({ ok: false, error: "Relay refused the connection" });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();

    const relayInput = container.querySelector<HTMLInputElement>(
      'input[placeholder="http://your-host:9137"]',
    );
    const teamInput = container.querySelector<HTMLInputElement>(
      'input[placeholder="Acme Crew"]',
    );
    const displayInput = container.querySelector<HTMLInputElement>(
      'input[placeholder="How you appear on the board"]',
    );
    expect(relayInput?.value).toBe("http://127.0.0.1:9137");
    expect(teamInput).not.toBeNull();
    expect(displayInput).not.toBeNull();
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      if (teamInput) {
        setValue?.call(teamInput, "Fabric Team");
        teamInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (displayInput) {
        setValue?.call(displayInput, "Owner");
        displayInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    const createButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Create team",
    );
    expect(createButton).toBeDefined();
    expect(createButton?.disabled).toBe(false);
    await act(async () => createButton?.click());
    await flushEffects();

    expect(container.textContent).toContain("Relay refused the connection");
    expect(fetchJSON).toHaveBeenCalledWith(
      "/api/plugins/fabric-achievements/team/host/probe",
      expect.objectContaining({ method: "POST" }),
    );
    expect(
      fetchJSON.mock.calls.some(([url]) => String(url).endsWith("/team/create")),
    ).toBe(false);
  });

  it("keeps the newest membership response when refresh and leave overlap", async () => {
    const staleRefresh = deferred<Record<string, unknown>>();
    let leaderboardCalls = 0;
    const membership = {
      team_name: "Old Team",
      display_name: "Owner",
      role: "owner",
      member_id: "member-1",
    };
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        leaderboardCalls += 1;
        if (leaderboardCalls === 1) {
          return Promise.resolve({ ok: true, membership, publish_opt_in: false, leaderboard: [] });
        }
        return staleRefresh.promise;
      }
      if (url.includes("/team/leaderboard?refresh=false")) {
        return Promise.resolve({ ok: true, membership: null, leaderboard: [] });
      }
      if (url.endsWith("/team/leave")) {
        return Promise.resolve({ ok: true, membership: null, publish_opt_in: false });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const refresh = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Refresh",
    );
    const leave = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Leave team",
    );
    await act(async () => refresh?.click());
    await act(async () => leave?.click());
    await flushEffects();
    expect(container.textContent).toContain("Join a leaderboard");

    await act(async () => {
      staleRefresh.resolve({ ok: true, membership, publish_opt_in: false, leaderboard: [] });
      await staleRefresh.promise;
    });
    expect(container.textContent).toContain("Join a leaderboard");
    expect(container.textContent).not.toContain("Old Team");
  });

  it.each([
    ["unpublish", "Stop sharing", "/team/settings"],
    ["rotate", "Reset invite", "/team/rotate"],
    ["leave", "Leave team", "/team/leave"],
  ])("keeps a successful %s visible when the follow-up roster read fails", async (action, buttonText, endpoint) => {
    const membership = {
      team_name: "Fabric Team",
      display_name: "Owner",
      role: "owner",
      member_id: "member-1",
      invite_code: "fbl1_old",
    };
    const response = action === "leave"
      ? { ok: true, membership: null, publish_opt_in: false, leaderboard: [] }
      : action === "rotate"
        ? { ok: true, membership: { ...membership, invite_code: "fbl1_new" }, publish_opt_in: true }
        : { ok: true, membership, publish_opt_in: false, pending_unpublish: false, last_published_at: null };

    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({
          ok: true,
          membership,
          publish_opt_in: true,
          last_published_at: 100,
          leaderboard: [],
        });
      }
      if (url.endsWith(endpoint)) return Promise.resolve(response);
      if (url.includes("/team/leaderboard?refresh=false")) {
        return Promise.reject(new Error("roster read failed"));
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const actionButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === buttonText,
    );
    expect(actionButton).toBeDefined();
    await act(async () => actionButton?.click());
    await flushEffects();

    expect(container.querySelector('[role="alert"]')?.textContent).toContain("roster read failed");
    if (action === "leave") {
      expect(container.textContent).toContain("Join a leaderboard");
      expect(container.textContent).not.toContain("Fabric Team");
    } else if (action === "rotate") {
      expect(container.querySelector<HTMLInputElement>(".ha-invite-row input")?.value).toBe("fbl1_new");
    } else {
      expect(container.textContent).toContain("Viewing only");
      expect(container.textContent).not.toContain("Your score is being shared");
    }
  });

  it("shows a failed retraction truthfully and announces the error", async () => {
    const membership = {
      team_name: "Fabric Team",
      display_name: "Owner",
      role: "owner",
      member_id: "member-1",
    };
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({ ok: true, membership, publish_opt_in: true, leaderboard: [] });
      }
      if (url.endsWith("/team/settings")) {
        return Promise.resolve({
          ok: false,
          error: "unpublish refused",
          membership,
          publish_opt_in: false,
          pending_unpublish: true,
          leaderboard: [],
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const stop = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Stop sharing",
    );
    await act(async () => stop?.click());
    await flushEffects();

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "unpublish refused",
    );
    expect(container.textContent).toContain("Your score may still be visible");
    expect(container.textContent).toContain("Retry retraction");
    expect(container.textContent).not.toContain("Viewing only");
  });

  it("offers a real publish retry without conflating generic relay errors", async () => {
    const membership = {
      team_name: "Fabric Team",
      display_name: "Owner",
      role: "owner",
      member_id: "member-1",
    };
    let retried = false;
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({
          ok: true,
          membership,
          publish_opt_in: true,
          publish_error: "publish refused",
          last_error: "roster also unavailable",
          leaderboard: [],
        });
      }
      if (url.endsWith("/team/publish")) {
        retried = true;
        return Promise.resolve({ ok: true, membership, publish_opt_in: true });
      }
      if (url.includes("/team/leaderboard?refresh=false")) {
        return Promise.resolve({
          ok: true,
          membership,
          publish_opt_in: true,
          publish_error: null,
          last_error: "roster unavailable",
          leaderboard: [],
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    expect(container.textContent).toContain("Sharing needs attention");
    const publish = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Publish now",
    );
    expect(publish).toBeDefined();
    await act(async () => publish?.click());
    await flushEffects();
    expect(retried).toBe(true);
    expect(container.textContent).not.toContain("Sharing needs attention");
    expect(container.textContent).toContain("Stop sharing");
  });

  it("keeps the latest clipboard result and exposes table semantics", async () => {
    const writes: Array<ReturnType<typeof deferred<void>>> = [];
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn(() => {
          const write = deferred<void>();
          writes.push(write);
          return write.promise;
        }),
      },
    });
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({
          ok: true,
          membership: {
            team_name: "Fabric Team",
            display_name: "Owner",
            role: "owner",
            member_id: "member-1",
            invite_code: "fbl1_test",
          },
          publish_opt_in: true,
          leaderboard: [{
            member_id: "member-1",
            display_name: "Owner",
            role: "owner",
            rank: 1,
            score: 42,
            unlocked_count: 3,
            total_count: 5,
            highest_tier: "Bronze",
            has_published: true,
          }],
        });
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    expect(container.querySelector('[role="table"]')).not.toBeNull();
    expect(container.querySelectorAll('[role="columnheader"]')).toHaveLength(6);
    expect(container.querySelectorAll('[role="row"]')).toHaveLength(2);

    const copy = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Copy invite",
    );
    await act(async () => copy?.click());
    await act(async () => copy?.click());
    await act(async () => {
      writes[1].resolve();
      await writes[1].promise;
    });
    expect(container.textContent).toContain("Copied ✓");
    await act(async () => {
      writes[0].reject(new Error("denied"));
      await writes[0].promise.catch(() => undefined);
    });
    expect(container.textContent).toContain("Copied ✓");
    expect(container.textContent).not.toContain("Copy failed");
  });

  it("invalidates clipboard feedback when the invite rotates", async () => {
    const oldWrite = deferred<void>();
    const rotateReload = deferred<Record<string, unknown>>();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(() => oldWrite.promise) },
    });
    const membership = {
      team_name: "Fabric Team",
      display_name: "Owner",
      role: "owner",
      member_id: "member-1",
      invite_code: "fbl1_old",
    };
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) {
        return Promise.resolve({ ok: true, membership, publish_opt_in: false, leaderboard: [] });
      }
      if (url.endsWith("/team/rotate")) return Promise.resolve({ ok: true });
      if (url.includes("/team/leaderboard?refresh=false")) {
        return rotateReload.promise;
      }
      if (url.endsWith("/team/host/status")) {
        return Promise.resolve({ ok: true, tailscale: {}, local_relay: {}, managed_relay: {} });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const copy = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Copy invite",
    );
    await act(async () => copy?.click());
    const rotate = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Reset invite",
    );
    expect(rotate).toBeDefined();
    await act(async () => {
      rotate?.click();
      await Promise.resolve();
    });

    const observed: string[] = [];
    const observer = new MutationObserver(() => {
      const invite = container.querySelector<HTMLInputElement>(".ha-invite-row input")?.value;
      const label = Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent?.includes("Copy") || button.textContent?.includes("Copied"),
      )?.textContent;
      observed.push(`${invite}:${label}`);
    });
    observer.observe(container, { childList: true, subtree: true, characterData: true });

    await act(async () => {
      rotateReload.resolve({
        ok: true,
        membership: { ...membership, invite_code: "fbl1_new" },
        publish_opt_in: false,
        leaderboard: [],
      });
      oldWrite.resolve();
      await Promise.all([rotateReload.promise, oldWrite.promise]);
    });
    observer.disconnect();

    expect(container.querySelector<HTMLInputElement>(".ha-invite-row input")?.value).toBe("fbl1_new");
    expect(observed).not.toContain("fbl1_new:Copied ✓");
    expect(container.textContent).not.toContain("Copied ✓");
    expect(container.textContent).toContain("Copy invite");
  });

  it("labels relay startup as starting", async () => {
    const start = deferred<Record<string, unknown>>();
    const stopped = {
      ok: true,
      tailscale: { installed: false, running: false },
      local_relay: { ok: false },
      shareable_relay: { ok: false },
      managed_relay: { managed: false, running: false },
      default_port: 9137,
    };
    fetchJSON.mockImplementation((url: string) => {
      if (url.endsWith("/achievements")) return new Promise(() => {});
      if (url.endsWith("/team/leaderboard")) return Promise.resolve({ ok: true, membership: null });
      if (url.endsWith("/team/host/status")) return Promise.resolve(stopped);
      if (url.endsWith("/team/host/start")) return start.promise;
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const host = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Host on this machine",
    );
    await act(async () => host?.click());
    expect(container.textContent).toContain("Starting…");
    await act(async () => {
      start.resolve(stopped);
      await start.promise;
    });
  });
});
