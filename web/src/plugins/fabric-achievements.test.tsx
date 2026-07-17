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

  it("does not reclassify a matching manual relay URL as auto-filled", async () => {
    const manualRelay = "http://127.0.0.1:9137";
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
          local_relay: { ok: statusCalls === 2 },
          managed_relay: { managed: false, running: false },
          default_port: 9137,
          suggested_relay_url: statusCalls === 2 ? manualRelay : null,
          suggested_is_shareable: false,
          relay_live: statusCalls === 2,
        });
      }
      return Promise.resolve({ ok: true });
    });

    await renderLeaderboard();
    const relayInput = container.querySelector<HTMLInputElement>(
      'input[placeholder="http://your-host:9137"]',
    );
    expect(relayInput).not.toBeNull();
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      if (relayInput) {
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
});
