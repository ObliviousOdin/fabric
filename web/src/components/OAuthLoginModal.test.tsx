// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OAuthLoginModal } from "./OAuthLoginModal";
import {
  api,
  setManagementProfile,
  type OAuthProvider,
  type ProviderAccountResult,
} from "@/lib/api";

const provider: OAuthProvider = {
  id: "nous",
  name: "Nous Portal",
  flow: "device_code",
  cli_command: "fabric auth add nous",
  docs_url: "https://example.invalid/docs",
  status: { logged_in: false },
};

const managedProvider: OAuthProvider = {
  ...provider,
  id: "openai-codex",
  name: "OpenAI Codex (ChatGPT)",
};

function providerAccountResult(revision: number): ProviderAccountResult {
  const request = {
    request_id: "par_0123456789abcdef01234567",
    provider_id: "openai-codex" as const,
    status: "requested" as const,
    handoff_state: "offered" as const,
    device_label: "front desk",
    requested_at: "2026-07-11T12:00:00Z",
    updated_at: "2026-07-11T12:00:00Z",
    expires_at: "2026-07-18T12:00:00Z",
    notification_handoff_at: null,
    decision_at: null,
    decision_source: null,
    decision_reason: null,
  };
  return {
    created: revision === 1,
    request: revision === 0 ? null : request,
    snapshot: {
      provider_id: "openai-codex",
      revision,
      ownership_epoch: revision === 0 ? 0 : 1,
      desired_ownership: revision === 0 ? "unselected" : "fabric_managed",
      active_request_id: revision === 0 ? null : request.request_id,
      active_request: revision === 0 ? null : request,
      pruned_terminal_count: 0,
      requests: revision === 0 ? [] : [request],
      handoff:
        revision === 0
          ? null
          : {
              channel: "email",
              uri: "mailto:server-owned@example.test?subject=SERVER%20OWNED",
              delivery_verified: false,
            },
    },
  };
}

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("OAuthLoginModal device polling", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    vi.spyOn(window, "open").mockReturnValue({
      closed: false,
      close: vi.fn(),
      location: { replace: vi.fn() },
      opener: null,
    } as unknown as Window);
    setManagementProfile("");
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
    setManagementProfile("");
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("keeps polling single-flight while the previous request is pending", async () => {
    let resolvePoll!: (value: {
      session_id: string;
      status: "pending";
    }) => void;
    const pendingPoll = new Promise<{
      session_id: string;
      status: "pending";
    }>((resolve) => {
      resolvePoll = resolve;
    });

    vi.spyOn(api, "startOAuthLogin").mockResolvedValue({
      expires_in: 900,
      flow: "device_code",
      poll_interval: 5,
      session_id: "web-single-flight",
      user_code: "CODE-1234",
      verification_url: "https://example.invalid/device",
    });
    const pollSpy = vi
      .spyOn(api, "pollOAuthSession")
      .mockReturnValue(pendingPoll);
    vi.spyOn(api, "cancelOAuthSession").mockResolvedValue({ ok: true });

    await act(async () => {
      root.render(
        <OAuthLoginModal
          provider={provider}
          onClose={vi.fn()}
          onError={vi.fn()}
          onSuccess={vi.fn()}
        />,
      );
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      vi.advanceTimersByTime(4_100);
      await Promise.resolve();
    });

    expect(pollSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolvePoll({ session_id: "web-single-flight", status: "pending" });
      await Promise.resolve();
      await Promise.resolve();
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
    });

    expect(pollSpy).toHaveBeenCalledTimes(2);
  });

  it("ignores a late approval after the visible session has expired", async () => {
    let resolvePoll!: (value: {
      session_id: string;
      status: "approved";
    }) => void;
    const pendingPoll = new Promise<{
      session_id: string;
      status: "approved";
    }>((resolve) => {
      resolvePoll = resolve;
    });
    const onSuccess = vi.fn();

    vi.spyOn(api, "startOAuthLogin").mockResolvedValue({
      expires_in: 3,
      flow: "device_code",
      poll_interval: 5,
      session_id: "web-expiring-session",
      user_code: "CODE-1234",
      verification_url: "https://example.invalid/device",
    });
    vi.spyOn(api, "pollOAuthSession").mockReturnValue(pendingPoll);
    const cancelSpy = vi
      .spyOn(api, "cancelOAuthSession")
      .mockResolvedValue({ ok: true });

    await act(async () => {
      root.render(
        <OAuthLoginModal
          provider={provider}
          onClose={vi.fn()}
          onError={vi.fn()}
          onSuccess={onSuccess}
        />,
      );
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      vi.advanceTimersByTime(3_100);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(cancelSpy).toHaveBeenCalledWith(
      "nous",
      "web-expiring-session",
      "current",
    );

    await act(async () => {
      resolvePoll({
        session_id: "web-expiring-session",
        status: "approved",
      });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("opens only the server-owned durable managed-access handoff", async () => {
    const replace = vi.fn();
    vi.mocked(window.open).mockReturnValue({
      closed: false,
      close: vi.fn(),
      location: { replace },
      opener: null,
    } as unknown as Window);
    vi.spyOn(api, "getSystemStats").mockResolvedValue({
      hostname: "front desk",
    } as Awaited<ReturnType<typeof api.getSystemStats>>);
    const getAccount = vi
      .spyOn(api, "getProviderAccount")
      .mockResolvedValue(providerAccountResult(0));
    const createRequest = vi
      .spyOn(api, "createProviderManagedRequest")
      .mockResolvedValue(providerAccountResult(1));
    const recordHandoff = vi
      .spyOn(api, "recordProviderAccountHandoff")
      .mockRejectedValue(new Error("handoff audit temporarily unavailable"));
    setManagementProfile("origin-profile");

    await act(async () => {
      root.render(
        <OAuthLoginModal
          provider={managedProvider}
          onClose={vi.fn()}
          onError={vi.fn()}
          onSuccess={vi.fn()}
        />,
      );
    });

    const managedChoice = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("Fabric-managed"));
    expect(managedChoice).toBeDefined();
    await act(async () => {
      managedChoice?.click();
      await Promise.resolve();
    });
    setManagementProfile("other-profile");
    const emailButton = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("email handoff"));
    expect(emailButton).toBeDefined();
    await act(async () => {
      emailButton?.click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getAccount).toHaveBeenCalledWith("openai-codex", "origin-profile");
    expect(createRequest).toHaveBeenCalledWith(
      "openai-codex",
      "front desk",
      0,
      "origin-profile",
    );
    expect(recordHandoff).toHaveBeenCalledWith(
      "openai-codex",
      "par_0123456789abcdef01234567",
      1,
      "origin-profile",
    );
    expect(replace).toHaveBeenCalledWith(
      "mailto:server-owned@example.test?subject=SERVER%20OWNED",
    );
  });

  it("pins a personal start to the freshly read account revision", async () => {
    const getAccount = vi
      .spyOn(api, "getProviderAccount")
      .mockResolvedValue(providerAccountResult(7));
    const startLogin = vi
      .spyOn(api, "startOAuthLogin")
      .mockRejectedValue(new Error("stale_revision"));
    setManagementProfile("origin-profile");

    await act(async () => {
      root.render(
        <OAuthLoginModal
          provider={managedProvider}
          onClose={vi.fn()}
          onError={vi.fn()}
          onSuccess={vi.fn()}
        />,
      );
    });
    const personalChoice = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("My account"));

    await act(async () => {
      personalChoice?.click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getAccount).toHaveBeenCalledWith("openai-codex", "origin-profile");
    expect(startLogin).toHaveBeenCalledWith("openai-codex", "origin-profile", {
      expectedRevision: 7,
    });
    expect(document.body.textContent).toContain("stale_revision");
  });

  it("surfaces blocked navigation and cancels the created backend session", async () => {
    vi.mocked(window.open).mockReturnValue(null);
    vi.spyOn(api, "getProviderAccount").mockResolvedValue(
      providerAccountResult(0),
    );
    vi.spyOn(api, "startOAuthLogin").mockResolvedValue({
      expires_in: 900,
      flow: "device_code",
      poll_interval: 5,
      session_id: "blocked-session",
      user_code: "CODE-1234",
      verification_url: "https://accounts.x.ai/device",
    });
    const cancel = vi
      .spyOn(api, "cancelOAuthSession")
      .mockResolvedValue({ ok: true });

    await act(async () => {
      root.render(
        <OAuthLoginModal
          provider={managedProvider}
          onClose={vi.fn()}
          onError={vi.fn()}
          onSuccess={vi.fn()}
        />,
      );
    });
    const personalChoice = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("My account"));
    await act(async () => {
      personalChoice?.click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(document.body.textContent).toContain("sign-in page was blocked");
    expect(cancel).toHaveBeenCalledWith(
      "openai-codex",
      "blocked-session",
      "current",
    );
  });

  it("offers an explicit takeover after an OAuth conflict", async () => {
    vi.spyOn(api, "getProviderAccount")
      .mockResolvedValueOnce(providerAccountResult(7))
      .mockResolvedValueOnce(providerAccountResult(8));
    const startLogin = vi
      .spyOn(api, "startOAuthLogin")
      .mockRejectedValueOnce(
        new Error('409: {"error":{"code":"oauth_in_progress"}}'),
      )
      .mockResolvedValueOnce({
        expires_in: 900,
        flow: "device_code",
        poll_interval: 5,
        session_id: "takeover-session",
        user_code: "CODE-1234",
        verification_url: "https://auth.openai.com/codex/device",
      });
    vi.spyOn(api, "cancelOAuthSession").mockResolvedValue({ ok: true });

    await act(async () => {
      root.render(
        <OAuthLoginModal
          provider={managedProvider}
          onClose={vi.fn()}
          onError={vi.fn()}
          onSuccess={vi.fn()}
        />,
      );
    });
    const personalChoice = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("My account"));
    await act(async () => {
      personalChoice?.click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const takeover = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("Take over sign-in"));
    expect(takeover).toBeDefined();
    await act(async () => {
      takeover?.click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(startLogin).toHaveBeenNthCalledWith(
      1,
      "openai-codex",
      "current",
      { expectedRevision: 7 },
    );
    expect(startLogin).toHaveBeenNthCalledWith(
      2,
      "openai-codex",
      "current",
      { expectedRevision: 8, takeover: true },
    );
    expect(document.body.textContent).toContain("CODE-1234");
  });

  it("keeps account navigation disabled while a managed request is pending", async () => {
    let rejectAccount!: (reason: Error) => void;
    const pendingAccount = new Promise<ProviderAccountResult>(
      (_resolve, reject) => {
        rejectAccount = reject;
      },
    );
    const close = vi.fn();
    vi.mocked(window.open).mockReturnValue({
      closed: false,
      close,
      location: { replace: vi.fn() },
      opener: null,
    } as unknown as Window);
    vi.spyOn(api, "getSystemStats").mockRejectedValue(new Error("offline"));
    vi.spyOn(api, "getProviderAccount").mockReturnValue(pendingAccount);
    const createRequest = vi.spyOn(api, "createProviderManagedRequest");

    await act(async () => {
      root.render(
        <OAuthLoginModal
          provider={managedProvider}
          onClose={vi.fn()}
          onError={vi.fn()}
          onSuccess={vi.fn()}
        />,
      );
    });
    const managedChoice = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("Fabric-managed"));
    await act(async () => managedChoice?.click());
    const emailButton = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("email handoff"));
    await act(async () => emailButton?.click());

    const backButton = Array.from(
      document.body.querySelectorAll("button"),
    ).find((button) => button.textContent?.includes("Back to account choice"));
    expect((backButton as HTMLButtonElement).disabled).toBe(true);
    backButton?.click();
    expect(createRequest).not.toHaveBeenCalled();

    await act(async () => {
      rejectAccount(new Error("request inspection failed"));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(close).toHaveBeenCalled();
  });

  it("portals the modal, traps initial focus, and closes on Escape", async () => {
    const onClose = vi.fn();
    await act(async () => {
      root.render(
        <OAuthLoginModal
          provider={managedProvider}
          onClose={onClose}
          onError={vi.fn()}
          onSuccess={vi.fn()}
        />,
      );
    });

    const dialog = document.body.querySelector<HTMLElement>("[role=dialog]");
    expect(dialog).not.toBeNull();
    expect(container.querySelector("[role=dialog]")).toBeNull();
    expect(dialog?.contains(document.activeElement)).toBe(true);
    await act(async () => {
      dialog?.dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: "Escape" }),
      );
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
