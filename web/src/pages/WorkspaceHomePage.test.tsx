// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getCronSummary, getSessions, getStatus } = vi.hoisted(() => ({
  getCronSummary: vi.fn(),
  getSessions: vi.fn(),
  getStatus: vi.fn(),
}));

vi.mock("@/contexts/useProfileScope", () => ({
  useProfileScope: () => ({ profile: "ops", currentProfile: "default" }),
}));
vi.mock("@/lib/api", () => ({
  api: { getCronSummary, getSessions, getStatus },
}));

import WorkspaceHomePage from "./WorkspaceHomePage";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("WorkspaceHomePage projection loading", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    getCronSummary.mockReset();
    getSessions.mockReset();
    getStatus.mockReset();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("paints successful sections without waiting for a stalled projection", async () => {
    getStatus.mockReturnValue(new Promise(() => {}));
    getCronSummary.mockReturnValue(new Promise(() => {}));
    getSessions.mockResolvedValue({
      sessions: [
        {
          id: "session-1",
          title: "Quarterly operations review",
          preview: "Review open exceptions",
          source: "dashboard",
          last_active: Date.now() / 1000,
          is_active: true,
        },
      ],
      total: 1,
    });

    await act(async () => {
      root.render(
        <MemoryRouter>
          <WorkspaceHomePage />
        </MemoryRouter>,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Now");
    expect(container.textContent).toContain("Active threads");
    expect(container.textContent).toContain("Quarterly operations review");
    expect(container.textContent).toContain("Loading runtime state");
    expect(getCronSummary).toHaveBeenCalledWith("ops");
  });
});
