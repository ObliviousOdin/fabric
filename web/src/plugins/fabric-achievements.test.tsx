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
        return Promise.resolve({
          ok: true,
          membership: { ...membership, invite_code: "fbl1_new" },
          publish_opt_in: false,
          leaderboard: [],
        });
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
    await act(async () => rotate?.click());
    await flushEffects();
    expect(container.querySelector<HTMLInputElement>(".ha-invite-row input")?.value).toBe("fbl1_new");
    await act(async () => {
      oldWrite.resolve();
      await oldWrite.promise;
    });
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
