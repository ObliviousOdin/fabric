import { describe, expect, it } from "vitest";

import { formatCountdown } from "@/components/ui/time";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe("formatCountdown", () => {
  it("renders sub-minute deltas as seconds", () => {
    expect(formatCountdown(0)).toBe("in 0s");
    expect(formatCountdown(45_000)).toBe("in 45s");
    expect(formatCountdown(59_999)).toBe("in 59s");
  });

  it("shows seconds only inside the final two minutes", () => {
    expect(formatCountdown(MINUTE)).toBe("in 1m 0s");
    expect(formatCountdown(90_000)).toBe("in 1m 30s");
    expect(formatCountdown(119_999)).toBe("in 1m 59s");
    // At exactly 2 minutes the ticker drops to 30 s, so seconds disappear.
    expect(formatCountdown(2 * MINUTE)).toBe("in 2m");
  });

  it("renders minutes up to an hour", () => {
    expect(formatCountdown(14 * MINUTE)).toBe("in 14m");
    expect(formatCountdown(HOUR - 1)).toBe("in 59m");
  });

  it("renders hours + minutes up to a day", () => {
    expect(formatCountdown(HOUR)).toBe("in 1h 0m");
    expect(formatCountdown(2 * HOUR + 14 * MINUTE)).toBe("in 2h 14m");
    expect(formatCountdown(DAY - 1)).toBe("in 23h 59m");
  });

  it("renders days + hours beyond a day", () => {
    expect(formatCountdown(DAY)).toBe("in 1d 0h");
    expect(formatCountdown(2 * DAY + 4 * HOUR)).toBe("in 2d 4h");
  });

  it("renders past-due as overdue", () => {
    expect(formatCountdown(-1)).toBe("overdue");
    expect(formatCountdown(-90_000)).toBe("overdue");
  });
});
