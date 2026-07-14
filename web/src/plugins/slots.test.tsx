// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PluginSlot,
  registerSlot,
  unregisterPluginSlots,
} from "./slots";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

interface RailActionProps {
  label: string;
  active: boolean;
  navigate: (path: string) => void;
}

function RailAction({ label, active, navigate }: RailActionProps) {
  return (
    <button
      data-active={String(active)}
      onClick={() => navigate("/work?view=graph")}
    >
      {label}
    </button>
  );
}

describe("PluginSlot", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      unregisterPluginSlots("slot-test");
      root.unmount();
    });
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("passes host navigation props to a typed plugin component", async () => {
    const navigate = vi.fn();
    registerSlot("slot-test", "chat:rail", RailAction);

    await act(async () => {
      root.render(
        <PluginSlot
          name="chat:rail"
          slotProps={{ label: "Open graph", active: false, navigate }}
        />,
      );
    });

    expect(container.querySelector("button")?.dataset.active).toBe("false");

    await act(async () => {
      root.render(
        <PluginSlot
          name="chat:rail"
          slotProps={{ label: "Open graph", active: true, navigate }}
        />,
      );
    });

    const button = container.querySelector("button");
    expect(button?.dataset.active).toBe("true");
    button?.click();

    expect(navigate).toHaveBeenCalledWith("/work?view=graph");
  });

  it("renders late registrations and replaces the same plugin in place", async () => {
    await act(async () => {
      root.render(
        <PluginSlot name="chat:rail" fallback={<span>Nothing yet</span>} />,
      );
    });
    expect(container.textContent).toBe("Nothing yet");

    await act(async () => {
      registerSlot("slot-test", "chat:rail", () => <span>First card</span>);
    });
    expect(container.textContent).toBe("First card");

    await act(async () => {
      registerSlot("slot-test", "chat:rail", () => <span>Replacement</span>);
    });
    expect(container.textContent).toBe("Replacement");
  });
});
