import { describe, expect, it, vi } from "vitest";

import {
  classifyRestartPoll,
  GATEWAY_RESTART_ACTION,
  RESTART_RELOAD_DELAY_MS,
  RESTART_WATCH_ATTEMPTS,
  RESTART_WATCH_INTERVAL_MS,
  watchGatewayRestartOutcome,
  type RestartActionStatus,
} from "@/lib/gateway-restart";

const noSleep = () => Promise.resolve();

function statusSequence(seq: RestartActionStatus[]) {
  let i = 0;
  return vi.fn(() => {
    const st = seq[Math.min(i, seq.length - 1)];
    i += 1;
    return Promise.resolve(st);
  });
}

describe("CN3 restart poll classification (R25)", () => {
  it("keeps polling while the action is running", () => {
    expect(classifyRestartPoll({ running: true, exit_code: null })).toBe(
      "pending",
    );
    // running wins even if a stale exit_code rides along
    expect(classifyRestartPoll({ running: true, exit_code: 1 })).toBe(
      "pending",
    );
  });

  it("treats exit 0 as success", () => {
    expect(classifyRestartPoll({ running: false, exit_code: 0 })).toBe(
      "success",
    );
  });

  it("treats exit null as success — the no-service-install semantics", () => {
    // In no-service installs the spawned child becomes the foreground
    // gateway and never exits; a settled status with a null exit code must
    // never raise the manual-restart banner.
    expect(classifyRestartPoll({ running: false, exit_code: null })).toBe(
      "success",
    );
  });

  it("treats any non-zero exit as failure", () => {
    expect(classifyRestartPoll({ running: false, exit_code: 1 })).toBe(
      "failed",
    );
    expect(classifyRestartPoll({ running: false, exit_code: 143 })).toBe(
      "failed",
    );
    expect(classifyRestartPoll({ running: false, exit_code: -15 })).toBe(
      "failed",
    );
  });
});

describe("CN3 restart watch loop", () => {
  it("uses the shipped cadence constants (20 × 1.5 s, 4 s reload delay)", () => {
    expect(GATEWAY_RESTART_ACTION).toBe("gateway-restart");
    expect(RESTART_WATCH_ATTEMPTS).toBe(20);
    expect(RESTART_WATCH_INTERVAL_MS).toBe(1500);
    expect(RESTART_RELOAD_DELAY_MS).toBe(4000);
  });

  it("sleeps before the first poll (the child needs a moment to exist)", async () => {
    const calls: string[] = [];
    const getStatus = vi.fn(() => {
      calls.push("poll");
      return Promise.resolve({ running: false, exit_code: 0 });
    });
    const sleep = vi.fn((ms: number) => {
      calls.push(`sleep(${ms})`);
      return Promise.resolve();
    });
    await watchGatewayRestartOutcome({ getStatus, sleep });
    expect(calls[0]).toBe(`sleep(${RESTART_WATCH_INTERVAL_MS})`);
    expect(calls[1]).toBe("poll");
  });

  it("resolves success on the first settled zero-exit poll", async () => {
    const getStatus = statusSequence([
      { running: true, exit_code: null },
      { running: true, exit_code: null },
      { running: false, exit_code: 0 },
    ]);
    const outcome = await watchGatewayRestartOutcome({
      getStatus,
      sleep: noSleep,
    });
    expect(outcome).toEqual({ kind: "success" });
    expect(getStatus).toHaveBeenCalledTimes(3);
  });

  it("resolves success on a settled null-exit poll (R25)", async () => {
    const getStatus = statusSequence([
      { running: false, exit_code: null },
    ]);
    const outcome = await watchGatewayRestartOutcome({
      getStatus,
      sleep: noSleep,
    });
    expect(outcome).toEqual({ kind: "success" });
    expect(getStatus).toHaveBeenCalledTimes(1);
  });

  it("resolves failure with the exit code on non-zero exit", async () => {
    const getStatus = statusSequence([
      { running: true, exit_code: null },
      { running: false, exit_code: 7 },
    ]);
    const outcome = await watchGatewayRestartOutcome({
      getStatus,
      sleep: noSleep,
    });
    expect(outcome).toEqual({ kind: "failed", exitCode: 7 });
  });

  it("keeps polling through transient fetch errors", async () => {
    let calls = 0;
    const getStatus = vi.fn(() => {
      calls += 1;
      if (calls < 3) return Promise.reject(new Error("connection refused"));
      return Promise.resolve({ running: false, exit_code: 0 });
    });
    const outcome = await watchGatewayRestartOutcome({
      getStatus,
      sleep: noSleep,
    });
    expect(outcome).toEqual({ kind: "success" });
    expect(getStatus).toHaveBeenCalledTimes(3);
  });

  it("closes the window as window-closed (not failure) when still running", async () => {
    const getStatus = vi.fn(() =>
      Promise.resolve({ running: true, exit_code: null }),
    );
    const outcome = await watchGatewayRestartOutcome({
      getStatus,
      sleep: noSleep,
    });
    expect(outcome).toEqual({ kind: "window-closed" });
    expect(getStatus).toHaveBeenCalledTimes(RESTART_WATCH_ATTEMPTS);
  });

  it("closes the window as window-closed when every poll errors", async () => {
    const getStatus = vi.fn(() => Promise.reject(new Error("offline")));
    const outcome = await watchGatewayRestartOutcome({
      getStatus,
      sleep: noSleep,
      attempts: 5,
    });
    expect(outcome).toEqual({ kind: "window-closed" });
    expect(getStatus).toHaveBeenCalledTimes(5);
  });
});
