import { describe, expect, it } from "vitest";

import { assertMatchingInteractionReceipt } from "./use-mobile-gateway";

describe("interaction response receipts", () => {
  it("accepts only the exact approval request with one resolution", () => {
    expect(() =>
      assertMatchingInteractionReceipt(
        { request_id: "approval-2", resolved: 1 },
        "approval-2",
        { approval: true },
      ),
    ).not.toThrow();

    for (const receipt of [
      { request_id: "approval-1", resolved: 1 },
      { request_id: "approval-2", resolved: 0 },
      { request_id: "approval-2" },
      null,
    ]) {
      expect(() =>
        assertMatchingInteractionReceipt(receipt, "approval-2", {
          approval: true,
        }),
      ).toThrow("Response did not match the pending request");
    }
  });

  it("accepts a generic prompt receipt only for the exact request", () => {
    expect(() =>
      assertMatchingInteractionReceipt({ request_id: "secret-2" }, "secret-2"),
    ).not.toThrow();
    expect(() =>
      assertMatchingInteractionReceipt({ request_id: "secret-1" }, "secret-2"),
    ).toThrow("Response did not match the pending request");
  });
});
