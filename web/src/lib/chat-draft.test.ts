import { describe, expect, it } from "vitest";

import { composerDraftPayload, sanitizeComposerDraft } from "./chat-draft";

describe("sanitizeComposerDraft", () => {
  it("preserves multiline content but removes terminal control bytes", () => {
    expect(
      sanitizeComposerDraft("  /design hello\r\nworld\u001b[31m\u0007\u009b  "),
    ).toBe("/design hello\nworld[31m");
  });

  it("bounds drafts before they cross the PTY boundary", () => {
    expect(sanitizeComposerDraft("x".repeat(9_000))).toHaveLength(8_000);
  });
});

describe("composerDraftPayload", () => {
  it("uses bracketed paste without submitting the composer", () => {
    expect(composerDraftPayload("/design hello")).toBe(
      "\u001b[200~/design hello\u001b[201~",
    );
  });
});
