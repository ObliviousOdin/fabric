// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { isChatPath } from "@/app/routes";
import { usePersistentChatIdentity } from "./usePersistentChatIdentity";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function Probe() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const identity = usePersistentChatIdentity(
    isChatPath(location.pathname),
    searchParams.get("resume"),
    searchParams.get("profile") ?? "",
  );

  return (
    <>
      <output data-channel={identity.channel} data-profile={identity.profile}>
        {identity.resumeParam ?? "fresh"}
      </output>
      <button onClick={() => navigate("/workspace/home?filter=mine")}>Home</button>
      <button onClick={() => navigate("/workspace/chat?resume=B&profile=ops")}>Chat B</button>
    </>
  );
}

describe("usePersistentChatIdentity", () => {
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

  it("preserves PTY identity while hidden and adopts route state on return", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/workspace/chat?resume=A&profile=default"]}>
          <Probe />
        </MemoryRouter>,
      );
    });

    const output = () => container.querySelector("output")!;
    const firstChannel = output().dataset.channel;
    expect(output().textContent).toBe("A");

    await act(async () => {
      container.querySelectorAll("button")[0].click();
    });
    expect(output().textContent).toBe("A");
    expect(output().dataset.profile).toBe("default");
    expect(output().dataset.channel).toBe(firstChannel);

    await act(async () => {
      container.querySelectorAll("button")[1].click();
    });
    expect(output().textContent).toBe("B");
    expect(output().dataset.profile).toBe("ops");
    expect(output().dataset.channel).not.toBe(firstChannel);
  });
});
