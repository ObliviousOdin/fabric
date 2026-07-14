import { describe, expect, it } from "vitest";

import {
  CHAT_MEDIUM_MIN_WIDTH,
  CHAT_WIDE_MIN_WIDTH,
  chatViewportModeForWidth,
} from "./useChatViewportMode";

describe("chat viewport breakpoints", () => {
  it("uses compact below 1024, medium through 1439, and wide at 1440", () => {
    expect(chatViewportModeForWidth(CHAT_MEDIUM_MIN_WIDTH - 1)).toBe("compact");
    expect(chatViewportModeForWidth(CHAT_MEDIUM_MIN_WIDTH)).toBe("medium");
    expect(chatViewportModeForWidth(CHAT_WIDE_MIN_WIDTH - 1)).toBe("medium");
    expect(chatViewportModeForWidth(CHAT_WIDE_MIN_WIDTH)).toBe("wide");
  });
});
