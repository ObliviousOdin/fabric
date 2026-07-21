// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  getLoomStatus,
  getLoomHosts,
  getLoomProjects,
  getLoomDeployments,
} = vi.hoisted(() => ({
  getLoomStatus: vi.fn(),
  getLoomHosts: vi.fn(),
  getLoomProjects: vi.fn(),
  getLoomDeployments: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getLoomStatus,
    getLoomHosts,
    getLoomProjects,
    getLoomDeployments,
    createLoomHost: vi.fn(),
    createLoomProject: vi.fn(),
    planLoomDeploy: vi.fn(),
    loomDeploy: vi.fn(),
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
});
