// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { normalizeEpochSeconds } from "@/components/ui/time";
import { RelativeTime } from "@/components/ui/RelativeTime";

describe("normalizeEpochSeconds", () => {
  it("passes epoch-seconds numbers through (sessions dialect)", () => {
    expect(normalizeEpochSeconds(1_720_000_000)).toBe(1_720_000_000);
    expect(normalizeEpochSeconds(1_720_000_000.25)).toBe(1_720_000_000.25);
  });

  it("down-converts millisecond-magnitude numbers", () => {
    expect(normalizeEpochSeconds(1_720_000_000_000)).toBe(1_720_000_000);
  });

  it("parses ISO strings to epoch seconds (cron dialect)", () => {
    expect(normalizeEpochSeconds("2026-07-13T00:00:00Z")).toBe(
      Date.parse("2026-07-13T00:00:00Z") / 1000,
    );
    // Offset form must agree with the equivalent Z form.
    expect(normalizeEpochSeconds("2026-07-13T02:00:00+02:00")).toBe(
      normalizeEpochSeconds("2026-07-13T00:00:00Z"),
    );
  });

  it("treats numeric strings as epochs, not ISO", () => {
    expect(normalizeEpochSeconds("1720000000")).toBe(1_720_000_000);
    expect(normalizeEpochSeconds("1720000000000")).toBe(1_720_000_000);
  });

  it("returns null for nullish, empty, zero and garbage input", () => {
    expect(normalizeEpochSeconds(null)).toBeNull();
    expect(normalizeEpochSeconds(undefined)).toBeNull();
    expect(normalizeEpochSeconds("")).toBeNull();
    expect(normalizeEpochSeconds("   ")).toBeNull();
    expect(normalizeEpochSeconds(0)).toBeNull();
    expect(normalizeEpochSeconds(-5)).toBeNull();
    expect(normalizeEpochSeconds(Number.NaN)).toBeNull();
    expect(normalizeEpochSeconds("not a date")).toBeNull();
  });
});

describe("RelativeTime", () => {
  const reactActEnvironment = globalThis as typeof globalThis & {
    IS_REACT_ACT_ENVIRONMENT?: boolean;
  };
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

  it("renders epoch seconds and ISO strings identically", async () => {
    const seconds = Date.now() / 1000 - 120; // 2 minutes ago
    const iso = new Date(seconds * 1000).toISOString();

    await act(async () => {
      root.render(
        <>
          <RelativeTime value={seconds} />
          <RelativeTime value={iso} />
        </>,
      );
    });

    const nodes = container.querySelectorAll("time");
    expect(nodes).toHaveLength(2);
    expect(nodes[0].textContent).toBe("2m ago");
    expect(nodes[1].textContent).toBe("2m ago");
    expect(nodes[0].title).toBe(nodes[1].title);
  });

  it("renders an em dash for nullish values", async () => {
    await act(async () => {
      root.render(<RelativeTime value={null} />);
    });
    expect(container.textContent).toBe("—");
    expect(container.querySelector("time")).toBeNull();
  });
});
