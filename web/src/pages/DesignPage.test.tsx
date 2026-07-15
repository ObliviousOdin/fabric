// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PageHeaderContext } from "@/contexts/page-header-context";

import DesignPage from "./DesignPage";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function ChatLocation() {
  const location = useLocation();
  return <output data-testid="chat-location">{location.search}</output>;
}

describe("DesignPage", () => {
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

  it("prepares a reviewable /design draft before navigating to chat", async () => {
    await act(async () => {
      root.render(
        <PageHeaderContext.Provider
          value={{
            setAfterTitle: vi.fn(),
            setEnd: vi.fn(),
            setTitle: vi.fn(),
          }}
        >
          <MemoryRouter initialEntries={["/design"]}>
            <Routes>
              <Route element={<DesignPage />} path="/design" />
              <Route element={<ChatLocation />} path="/workspace/chat" />
            </Routes>
          </MemoryRouter>
        </PageHeaderContext.Provider>,
      );
    });

    const submit = container.querySelector<HTMLButtonElement>(
      'button[type="submit"]',
    );
    const brief = container.querySelector<HTMLTextAreaElement>("#design-brief");

    expect(submit?.disabled).toBe(true);
    expect(brief).not.toBeNull();

    await act(async () => {
      if (!brief) return;
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setValue?.call(brief, "Design a repository onboarding flow");
      brief.dispatchEvent(new Event("input", { bubbles: true }));
    });

    expect(submit?.disabled).toBe(false);

    await act(async () => submit?.click());

    const search = container.querySelector<HTMLOutputElement>(
      '[data-testid="chat-location"]',
    )?.textContent;
    const draft = new URLSearchParams(search ?? "").get("draft");
    const fresh = new URLSearchParams(search ?? "").get("fresh");

    expect(fresh).toBeTruthy();
    expect(draft).toContain("/design Design a repository onboarding flow");
    expect(draft).toContain("Fidelity: High fidelity.");
    expect(draft).toContain("current project's DESIGN.md");
  });
});
