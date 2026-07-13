// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RestartBanner } from "@/components/RestartBanner";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

const idleControls = {
  restartNeeded: false,
  restarting: false,
  restartMessage: null as string | null,
  restartError: null as string | null,
  restart: async () => {},
};

describe("RestartBanner (CN3)", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("renders nothing when there is nothing to say", async () => {
    await act(async () => {
      root.render(<RestartBanner controls={idleControls} />);
    });
    expect(container.textContent).toBe("");
  });

  it("renders the restart-needed banner with the default copy and action", async () => {
    await act(async () => {
      root.render(
        <RestartBanner
          controls={{ ...idleControls, restartNeeded: true }}
        />,
      );
    });
    expect(container.textContent).toContain(
      "Changes are saved. Restart the gateway for them to take effect.",
    );
    expect(container.textContent).toContain("Restart now");
    const button = container.querySelector("button");
    expect(button).not.toBeNull();
    expect(button?.disabled).toBe(false);
  });

  it("prefers restartError, then the page's neededMessage, over the default", async () => {
    await act(async () => {
      root.render(
        <RestartBanner
          controls={{
            ...idleControls,
            restartNeeded: true,
            restartError: "Gateway restart failed with exit 7.",
          }}
          neededMessage="Webhooks are enabled, but the gateway still needs a restart."
        />,
      );
    });
    expect(container.textContent).toContain(
      "Gateway restart failed with exit 7.",
    );
    expect(container.textContent).not.toContain("Webhooks are enabled");

    await act(async () => {
      root.render(
        <RestartBanner
          controls={{ ...idleControls, restartNeeded: true }}
          neededMessage="Webhooks are enabled, but the gateway still needs a restart."
          actionLabel="Restart gateway"
        />,
      );
    });
    expect(container.textContent).toContain("Webhooks are enabled");
    expect(container.textContent).toContain("Restart gateway");
  });

  it("disables the action and swaps the label while restarting", async () => {
    const restart = vi.fn(async () => {});
    await act(async () => {
      root.render(
        <RestartBanner
          controls={{
            ...idleControls,
            restartNeeded: true,
            restarting: true,
            restart,
          }}
        />,
      );
    });
    expect(container.textContent).toContain("Restarting…");
    expect(container.querySelector("button")?.disabled).toBe(true);
  });

  it("invokes restart() from the action button", async () => {
    const restart = vi.fn(async () => {});
    await act(async () => {
      root.render(
        <RestartBanner
          controls={{ ...idleControls, restartNeeded: true, restart }}
        />,
      );
    });
    await act(async () => {
      container.querySelector("button")?.click();
    });
    expect(restart).toHaveBeenCalledTimes(1);
  });

  it("renders the informational box only when no restart is needed", async () => {
    await act(async () => {
      root.render(
        <RestartBanner
          controls={{ ...idleControls, restartMessage: "Gateway restarting…" }}
        />,
      );
    });
    expect(container.textContent).toContain("Gateway restarting…");
    expect(container.querySelector("button")).toBeNull();

    // restartNeeded wins over a stale message (Webhooks ordering).
    await act(async () => {
      root.render(
        <RestartBanner
          controls={{
            ...idleControls,
            restartNeeded: true,
            restartMessage: "Gateway restarting…",
          }}
        />,
      );
    });
    expect(container.textContent).toContain("Restart now");
  });
});
