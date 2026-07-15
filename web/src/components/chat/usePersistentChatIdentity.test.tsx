// @vitest-environment jsdom

import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  MemoryRouter,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { isChatPath } from "@/app/routes";
import {
  reconcilePersistentChatLocation,
  usePersistentChatIdentity,
  useValueForChatIdentity,
} from "./usePersistentChatIdentity";

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
    searchParams.get("profile") ?? "default",
    searchParams.get("fresh"),
  );
  useEffect(() => {
    if (!isChatPath(location.pathname)) return;

    const replacement = reconcilePersistentChatLocation(
      location,
      identity.resumeParam,
    );
    if (replacement) navigate(replacement, { replace: true });
  }, [identity.resumeParam, location, navigate]);

  return (
    <>
      <output
        data-channel={identity.channel}
        data-location={`${location.pathname}${location.search}${location.hash}`}
        data-profile={identity.profile}
      >
        {identity.resumeParam ?? "fresh"}
      </output>
      <button onClick={() => navigate("/workspace/home?filter=mine")}>Home</button>
      <button
        onClick={() => navigate("/workspace/chat?panel=context#activity")}
      >
        Chat
      </button>
      <button onClick={() => navigate("/workspace/chat?resume=B&profile=ops")}>Chat B</button>
      <button
        onClick={() =>
          navigate(
            "/workspace/chat?fresh=request-1&panel=evidence#activity",
          )
        }
      >
        Fresh Chat
      </button>
    </>
  );
}

function IdentityValueProbe() {
  const [channel, setChannel] = useState("chat-a");
  const [appearance, setAppearance] = useState("dark");
  const sessionAppearance = useValueForChatIdentity(channel, appearance);

  return (
    <>
      <output data-channel={channel}>{sessionAppearance}</output>
      <button onClick={() => setAppearance("light")}>Light</button>
      <button onClick={() => setChannel("chat-b")}>Fresh chat</button>
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

  it("preserves PTY identity through ordinary bare Chat navigation", async () => {
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
    expect(output().textContent).toBe("A");
    expect(output().dataset.channel).toBe(firstChannel);
    expect(output().dataset.location).toBe(
      "/workspace/chat?panel=context&resume=A#activity",
    );

    await act(async () => {
      container.querySelectorAll("button")[2].click();
    });
    expect(output().textContent).toBe("B");
    expect(output().dataset.profile).toBe("ops");
    expect(output().dataset.channel).not.toBe(firstChannel);
  });

  it("uses an explicit fresh directive to replace the mounted identity", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/workspace/chat?resume=A&profile=default"]}>
          <Probe />
        </MemoryRouter>,
      );
    });

    const output = () => container.querySelector("output")!;
    const firstChannel = output().dataset.channel;

    await act(async () => {
      container.querySelectorAll("button")[0].click();
      container.querySelectorAll("button")[3].click();
    });

    expect(output().textContent).toBe("fresh");
    expect(output().dataset.channel).not.toBe(firstChannel);
    expect(output().dataset.location).toBe(
      "/workspace/chat?panel=evidence#activity",
    );
  });

  it("keeps spawn-time values stable until the PTY identity rotates", async () => {
    await act(async () => root.render(<IdentityValueProbe />));

    const output = () => container.querySelector("output")!;
    expect(output().textContent).toBe("dark");

    await act(async () => container.querySelectorAll("button")[0].click());
    expect(output().textContent).toBe("dark");

    await act(async () => container.querySelectorAll("button")[1].click());
    expect(output().dataset.channel).toBe("chat-b");
    expect(output().textContent).toBe("light");
  });
});
