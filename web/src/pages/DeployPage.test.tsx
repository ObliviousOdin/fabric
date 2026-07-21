// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  getLoomStatus,
  getLoomHosts,
  getLoomProjects,
  getLoomDeployments,
  planLoomDeploy,
  loomApply,
} = vi.hoisted(() => ({
  getLoomStatus: vi.fn(),
  getLoomHosts: vi.fn(),
  getLoomProjects: vi.fn(),
  getLoomDeployments: vi.fn(),
  planLoomDeploy: vi.fn(),
  loomApply: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getLoomStatus,
    getLoomHosts,
    getLoomProjects,
    getLoomDeployments,
    createLoomHost: vi.fn(),
    createLoomProject: vi.fn(),
    planLoomDeploy,
    loomDeploy: vi.fn(),
    loomApply,
    loomRollback: vi.fn(),
  },
}));

import DeployPage from "./DeployPage";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("DeployPage", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    getLoomStatus.mockReset();
    getLoomHosts.mockReset();
    getLoomProjects.mockReset();
    getLoomDeployments.mockReset();
    planLoomDeploy.mockReset();
    loomApply.mockReset();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("renders the status overview and the live deployment", async () => {
    getLoomStatus.mockResolvedValue({
      hosts: 1,
      projects: 1,
      deployments: 1,
      active: [
        {
          deployment: "d1",
          project_id: "p1",
          host_id: "h1",
          state: "active",
        },
      ],
    });
    getLoomHosts.mockResolvedValue([
      {
        id: "h1",
        name: "this-machine",
        kind: "local",
        state: "ready",
        address: "",
        user: "",
        port: 0,
        ssh_key_path: "",
        host_key_fingerprint: "",
        created_at: "",
        meta: {},
      },
    ]);
    getLoomProjects.mockResolvedValue([
      {
        id: "p1",
        name: "my-app",
        kind: "compose",
        source: "",
        config: {},
        created_at: "",
      },
    ]);
    getLoomDeployments.mockResolvedValue([
      {
        id: "d1",
        project_id: "p1",
        host_id: "h1",
        state: "active",
        source_ref: "",
        plan: null,
        active: true,
        previous_id: "",
        message: "",
        logs: "",
        created_at: "",
        updated_at: "",
      },
    ]);

    await act(async () => {
      root.render(<DeployPage />);
    });
    await flush();

    expect(container.textContent).toContain("Overview");
    expect(container.textContent).toContain("Live now");
    expect(container.textContent).toContain("my-app");
    expect(container.textContent).toContain("this-machine");
    expect(container.textContent).toContain("active");
    // A local host already exists, so the "Use this machine" affordance
    // reads as done rather than offering to add it again.
    expect(container.textContent).toContain("This machine is ready");
  });

  it("guides an empty account through the first deploy", async () => {
    getLoomStatus.mockResolvedValue({
      hosts: 0,
      projects: 0,
      deployments: 0,
      active: [],
    });
    getLoomHosts.mockResolvedValue([]);
    getLoomProjects.mockResolvedValue([]);
    getLoomDeployments.mockResolvedValue([]);

    await act(async () => {
      root.render(<DeployPage />);
    });
    await flush();

    expect(container.textContent).toContain("Use this machine");
    expect(container.textContent).toContain("No machines yet");
    expect(container.textContent).toContain("No projects yet");
    expect(container.textContent).toContain("No deployments yet");
    expect(container.textContent).toContain("Nothing is running yet");
  });

  it("applies the previewed deployment by id on confirm", async () => {
    getLoomStatus.mockResolvedValue({
      hosts: 1,
      projects: 1,
      deployments: 0,
      active: [],
    });
    getLoomHosts.mockResolvedValue([
      {
        id: "h1",
        name: "this-machine",
        kind: "local",
        state: "ready",
        address: "",
        user: "",
        port: 0,
        ssh_key_path: "",
        host_key_fingerprint: "",
        created_at: "",
        meta: {},
      },
    ]);
    getLoomProjects.mockResolvedValue([
      {
        id: "p1",
        name: "my-app",
        kind: "compose",
        source: "",
        config: {},
        created_at: "",
      },
    ]);
    getLoomDeployments.mockResolvedValue([]);

    const planned = {
      id: "dep-planned-1",
      project_id: "p1",
      host_id: "h1",
      state: "planned",
      source_ref: "",
      plan: {
        summary: "Deploy my-app",
        steps: [{ action: "Pull image", detail: "", kind: "create" }],
        has_destructive: false,
      },
      active: false,
      previous_id: "",
      message: "",
      logs: "",
      created_at: "",
      updated_at: "",
    };
    planLoomDeploy.mockResolvedValue(planned);
    loomApply.mockResolvedValue({
      ...planned,
      state: "active",
      plan: null,
      message: "Deployed",
      logs: "deploy ok",
    });

    await act(async () => {
      root.render(<DeployPage />);
    });
    await flush();

    // Choose the project and the machine.
    await selectOption("deploy-pick-project", "my-app");
    await selectOption("deploy-pick-host", "this-machine");

    // Preview the plan — this persists a PLANNED deployment and returns it.
    await clickButton("Preview the plan");
    expect(planLoomDeploy).toHaveBeenCalledWith({ project: "p1", host: "h1" });
    expect(container.textContent).toContain("Here's what will happen");

    // Confirm — must APPLY the exact previewed deployment by id, not replan.
    await clickButton("Deploy now");
    expect(loomApply).toHaveBeenCalledWith("dep-planned-1", {
      allow_destructive: false,
    });
    // The applied deployment's result is surfaced.
    expect(container.textContent).toContain("deploy ok");
  });

  // ── Interaction helpers ──────────────────────────────────────────────
  // The page renders custom Button/Select widgets; drive them by clicking
  // their DOM (React 18 delegates events at the root, so bubbling clicks
  // dispatched here reach the handlers).
  async function clickButton(label: string) {
    const btn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === label,
    );
    if (!btn) throw new Error(`button not found: ${label}`);
    await act(async () => {
      btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
  }

  async function selectOption(selectId: string, label: string) {
    const trigger = container.querySelector<HTMLButtonElement>(
      `#${selectId} button[role="combobox"]`,
    );
    if (!trigger) throw new Error(`select not found: ${selectId}`);
    await act(async () => {
      trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
    const option = Array.from(
      container.querySelectorAll('[role="option"]'),
    ).find((o) => o.textContent?.trim() === label);
    if (!option) throw new Error(`option not found: ${label}`);
    await act(async () => {
      option.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
  }
});
