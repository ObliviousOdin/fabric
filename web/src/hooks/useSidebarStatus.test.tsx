// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StatusResponse } from "@/lib/api";

const { getStatus } = vi.hoisted(() => ({ getStatus: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { getStatus } }));

import { useSidebarStatus } from "./useSidebarStatus";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function status(version: string): StatusResponse {
  return { version } as StatusResponse;
}

function Probe({ profile }: { profile: string }) {
  const result = useSidebarStatus(profile);
  return <output>{result?.version ?? "loading"}</output>;
}

describe("useSidebarStatus profile lifecycle", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
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

  it("refetches immediately and ignores a slower prior profile response", async () => {
    const profileA = deferred<StatusResponse>();
    const profileB = deferred<StatusResponse>();
    getStatus.mockReturnValueOnce(profileA.promise).mockReturnValueOnce(profileB.promise);

    await act(async () => root.render(<Probe profile="A" />));
    await act(async () => root.render(<Probe profile="B" />));
    expect(getStatus).toHaveBeenCalledTimes(2);
    expect(container.textContent).toBe("loading");

    await act(async () => profileB.resolve(status("B")));
    expect(container.textContent).toBe("B");

    await act(async () => profileA.resolve(status("A")));
    expect(container.textContent).toBe("B");
  });
});
