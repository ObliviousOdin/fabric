// @vitest-environment jsdom

import { afterEach, describe, expect, it } from "vitest";

import { acquireBodyScrollLock } from "./useBodyScrollLock";

describe("acquireBodyScrollLock", () => {
  afterEach(() => {
    document.body.style.removeProperty("overflow");
  });

  it("restores the first declaration only after the final out-of-order release", () => {
    document.body.style.setProperty("overflow", "scroll", "important");
    const releaseParent = acquireBodyScrollLock();
    const releaseChild = acquireBodyScrollLock();

    try {
      expect(document.body.style.overflow).toBe("hidden");

      releaseParent();
      expect(document.body.style.overflow).toBe("hidden");

      releaseChild();
      expect(document.body.style.overflow).toBe("scroll");
      expect(document.body.style.getPropertyPriority("overflow")).toBe(
        "important",
      );

      releaseChild();
      expect(document.body.style.overflow).toBe("scroll");
    } finally {
      releaseParent();
      releaseChild();
    }
  });
});
