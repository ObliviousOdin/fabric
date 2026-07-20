// @vitest-environment jsdom

import type { WorkAttention, WorkProjection } from "@fabric/shared";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkStatus } from "./work-status";

function attention(version: number): WorkAttention {
  return {
    actionable: true,
    allowed_actions: ["submit", "cancel"],
    attention_id: "attn_ffffffffffffffffffffffffffffffff",
    blocking: true,
    created_at: 1,
    expires_at: null,
    job_id: null,
    kind: "secret",
    object_type: "attention",
    public_payload: { prompt: `Registry token v${version}` },
    request_id: "22222222222222222222222222222222",
    resolved_at: null,
    run_id: null,
    runtime_session_id: "runtime-attention",
    sensitive: true,
    source_session_key: "stored-attention",
    state: "pending",
    terminal_reason: null,
    title: "Authentication is required",
    unknown_enums: [],
    updated_at: version,
    version,
  };
}

function projection(item: WorkAttention): WorkProjection {
  return {
    attention: { [item.attention_id]: item },
    cursor: item.version,
    gateway_id: "gateway-local",
    jobs: {},
    ledger_id: "ledger_11111111111111111111111111111111",
    next_page_token: null,
    phase: "current",
    profile_id: "profile_11111111111111111111111111111111",
    reset_ledger_hint: null,
    subject_versions: { [`attention:${item.attention_id}`]: item.version },
    unknown_subjects: {},
    watermark: item.version,
  };
}

describe("WorkStatus Attention form identity", () => {
  it("retains input and errors across ordinary rerenders and resets on revision change", async () => {
    const onRespond = vi
      .fn()
      .mockRejectedValue(new Error("Delivery uncertain."));
    const first = attention(1);
    const common = {
      activeRequestIds: new Set<string>(),
      background: {
        error: null,
        jobId: null,
        retryable: false,
        status: "idle" as const,
      },
      onAbandonBackground: vi.fn(),
      onRespond,
      onRetryBackground: vi.fn(async () => undefined),
      showAttention: true,
      status: "current" as const,
    };
    const view = render(
      <WorkStatus {...common} projection={projection(first)} />,
    );
    const input = view.container.querySelector("input");
    if (!input) throw new Error("missing Attention input");

    fireEvent.change(input, { target: { value: "one-time-secret" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => {
      expect(view.container.textContent).toContain("Delivery uncertain.");
    });

    view.rerender(
      <WorkStatus
        {...common}
        projection={projection({ ...first, title: "Cosmetic refresh" })}
      />,
    );
    expect(input.value).toBe("one-time-secret");
    expect(view.container.textContent).toContain("Delivery uncertain.");

    view.rerender(
      <WorkStatus {...common} projection={projection(attention(2))} />,
    );
    await waitFor(() => expect(input.value).toBe(""));
    expect(view.container.textContent).not.toContain("Delivery uncertain.");
  });

  it("offers only the exact approval action subset advertised by the item", async () => {
    const onRespond = vi.fn(async () => undefined);
    const item: WorkAttention = {
      ...attention(1),
      allowed_actions: ["session"],
      kind: "approval",
      public_payload: {
        command: "deploy --production",
        description: "Deploy the release",
      },
      sensitive: false,
    };
    const view = render(
      <WorkStatus
        activeRequestIds={new Set()}
        background={{
          error: null,
          jobId: null,
          retryable: false,
          status: "idle",
        }}
        onAbandonBackground={vi.fn()}
        onRespond={onRespond}
        onRetryBackground={vi.fn(async () => undefined)}
        projection={projection(item)}
        showAttention
        status="current"
      />,
    );

    const buttons = Array.from(view.container.querySelectorAll("button"));
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Allow for session",
    ]);
    fireEvent.click(buttons[0]!);
    await waitFor(() => {
      expect(onRespond).toHaveBeenCalledWith(
        item.attention_id,
        "session",
        undefined,
      );
    });
  });

  it("fails closed when an actionable item has no recognized response action", () => {
    const item: WorkAttention = {
      ...attention(1),
      allowed_actions: ["future_action"],
    };
    const view = render(
      <WorkStatus
        activeRequestIds={new Set()}
        background={{
          error: null,
          jobId: null,
          retryable: false,
          status: "idle",
        }}
        onAbandonBackground={vi.fn()}
        onRespond={vi.fn(async () => undefined)}
        onRetryBackground={vi.fn(async () => undefined)}
        projection={projection(item)}
        showAttention
        status="current"
      />,
    );

    expect(view.container.textContent).toContain(
      "This Attention item has no compatible response action.",
    );
    expect(view.container.querySelectorAll("button")).toHaveLength(0);
    expect(view.container.querySelector("input")).toBeNull();
  });

  it("does not expose Attention controls while the projection is stale", () => {
    const item = attention(1);
    const view = render(
      <WorkStatus
        activeRequestIds={new Set()}
        background={{
          error: null,
          jobId: null,
          retryable: false,
          status: "idle",
        }}
        onAbandonBackground={vi.fn()}
        onRespond={vi.fn(async () => undefined)}
        onRetryBackground={vi.fn(async () => undefined)}
        projection={projection(item)}
        showAttention
        status="error"
      />,
    );

    expect(view.container.querySelector("input")).toBeNull();
    expect(view.container.querySelectorAll("button")).toHaveLength(0);
  });
});
