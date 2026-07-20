import { describe, expect, it } from "vitest";

import additiveFutureFixture from "../../mobile/contracts/fabric-work-v1/additive-future.json";
import bootstrapPage1Fixture from "../../mobile/contracts/fabric-work-v1/bootstrap-page-1.json";
import bootstrapPage2Fixture from "../../mobile/contracts/fabric-work-v1/bootstrap-page-2.json";
import deltaFixture from "../../mobile/contracts/fabric-work-v1/delta.json";
import replacedLedgerFixture from "../../mobile/contracts/fabric-work-v1/replaced-ledger.json";
import sensitiveAttentionFixture from "../../mobile/contracts/fabric-work-v1/sensitive-attention.json";
import terminalFixture from "../../mobile/contracts/fabric-work-v1/terminal.json";
import tombstoneFixture from "../../mobile/contracts/fabric-work-v1/tombstone.json";
import {
  parseWorkCursorReset,
  parseWorkSyncPage,
  type WorkSyncPage,
} from "./work-contract";
import {
  WorkSyncApplyError,
  applyWorkCursorReset,
  applyWorkSyncPage,
  createWorkProjection,
  type WorkProjection,
  type WorkSyncScope,
} from "./work-sync";

const scope: WorkSyncScope = {
  gateway_id: "gateway-local",
  profile_id: "profile_11111111111111111111111111111111",
};

function page(fixture: unknown): WorkSyncPage {
  const result = parseWorkSyncPage(fixture);
  if (result.kind !== "verified")
    throw new Error(`bad fixture: ${result.kind}`);
  return result.page;
}

function bootstrapped(): WorkProjection {
  const first = applyWorkSyncPage(
    createWorkProjection(scope),
    page(bootstrapPage1Fixture),
    { ...scope, page_token: null },
  );
  return applyWorkSyncPage(first, page(bootstrapPage2Fixture), {
    ...scope,
    page_token: first.next_page_token,
  });
}

describe("fabric.work sync projection", () => {
  it("applies every bootstrap page before publishing its fixed cursor", () => {
    const empty = createWorkProjection(scope);
    const first = applyWorkSyncPage(empty, page(bootstrapPage1Fixture), {
      ...scope,
      page_token: null,
    });

    expect(first).toMatchObject({
      phase: "bootstrapping",
      ledger_id: "ledger_11111111111111111111111111111111",
      cursor: null,
      watermark: 100,
      next_page_token: "work-page-v1.first-to-second",
    });
    expect(Object.keys(first.jobs)).toEqual([
      "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ]);
    expect(Object.keys(first.attention)).toEqual([
      "attn_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    ]);

    const complete = applyWorkSyncPage(first, page(bootstrapPage2Fixture), {
      ...scope,
      page_token: first.next_page_token,
    });
    expect(complete).toMatchObject({
      phase: "current",
      cursor: 100,
      watermark: 100,
      next_page_token: null,
    });
    expect(Object.keys(complete.jobs).sort()).toEqual([
      "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    ]);
  });

  it("fails closed on a missing or wrong bootstrap continuation token", () => {
    const initial = createWorkProjection(scope);
    const first = applyWorkSyncPage(initial, page(bootstrapPage1Fixture), {
      ...scope,
      page_token: null,
    });
    const before = structuredClone(first);

    expect(() =>
      applyWorkSyncPage(first, page(bootstrapPage2Fixture), {
        ...scope,
        page_token: "wrong-token",
      }),
    ).toThrowError(
      expect.objectContaining<Partial<WorkSyncApplyError>>({
        code: "bootstrap_sequence_invalid",
      }),
    );
    expect(first).toEqual(before);
  });

  it("applies deltas, dedupes replayed events, and advances only after projection", () => {
    const initial = bootstrapped();
    const next = applyWorkSyncPage(initial, page(deltaFixture), {
      ...scope,
      after: 100,
    });

    expect(next.cursor).toBe(101);
    expect(next.jobs["job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]).toMatchObject({
      version: 2,
      status: "running",
    });

    const replay = applyWorkSyncPage(next, page(deltaFixture), scope);
    expect(replay).toEqual(next);
  });

  it("uses subject versions to ignore stale after-states while advancing the event cursor", () => {
    const running = applyWorkSyncPage(bootstrapped(), page(deltaFixture), {
      ...scope,
      after: 100,
    });
    const staleRaw = structuredClone(deltaFixture);
    staleRaw.watermark = 102;
    staleRaw.cursor = 102;
    staleRaw.events[0]!.event_id = 102;
    staleRaw.events[0]!.subject_version = 1;
    staleRaw.events[0]!.subject!.version = 1;
    staleRaw.events[0]!.subject!.status = "queued";
    const stale = applyWorkSyncPage(running, page(staleRaw), {
      ...scope,
      after: 101,
    });

    expect(stale.cursor).toBe(102);
    expect(stale.jobs["job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]).toMatchObject({
      version: 2,
      status: "running",
    });
  });

  it("persists tombstone versions so stale subjects cannot resurrect", () => {
    const running = applyWorkSyncPage(bootstrapped(), page(deltaFixture), {
      ...scope,
      after: 100,
    });
    const deleted = applyWorkSyncPage(running, page(tombstoneFixture), {
      ...scope,
      after: 101,
    });
    const attentionId = "attn_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";

    expect(deleted.attention[attentionId]).toBeUndefined();
    expect(deleted.subject_versions[`attention:${attentionId}`]).toBe(3);

    const staleRaw = structuredClone(sensitiveAttentionFixture);
    staleRaw.events[0]!.subject_id = attentionId;
    staleRaw.events[0]!.subject_version = 1;
    staleRaw.events[0]!.subject!.attention_id = attentionId;
    staleRaw.events[0]!.subject!.version = 1;
    const stale = applyWorkSyncPage(deleted, page(staleRaw), {
      ...scope,
      after: 103,
    });
    expect(stale.attention[attentionId]).toBeUndefined();
    expect(stale.cursor).toBe(104);
  });

  it("projects sensitive Attention and terminal Job after-states without values", () => {
    let state = applyWorkSyncPage(bootstrapped(), page(deltaFixture), {
      ...scope,
      after: 100,
    });
    state = applyWorkSyncPage(state, page(tombstoneFixture), {
      ...scope,
      after: 101,
    });
    state = applyWorkSyncPage(state, page(sensitiveAttentionFixture), {
      ...scope,
      after: 103,
    });
    state = applyWorkSyncPage(state, page(terminalFixture), {
      ...scope,
      after: 104,
    });

    expect(state).toMatchObject({ phase: "current", cursor: 105 });
    expect(
      state.attention["attn_ffffffffffffffffffffffffffffffff"],
    ).toMatchObject({
      sensitive: true,
      state: "pending",
    });
    expect(state.jobs["job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]).toMatchObject({
      version: 3,
      status: "succeeded",
    });
  });

  it("retains compatible unknown enums for display but never marks their object actionable", () => {
    const futureScope = {
      gateway_id: "future-gateway",
      profile_id: "profile_99999999999999999999999999999999",
    };
    const state = applyWorkSyncPage(
      createWorkProjection(futureScope),
      page(additiveFutureFixture),
      { ...futureScope, page_token: null },
    );
    const job = state.jobs["job_99999999999999999999999999999999"];

    expect(state.phase).toBe("current");
    expect(job).toMatchObject({ status: "materializing", actionable: false });
  });

  it("rejects gateway, profile, ledger, stale, and future cursor drift", () => {
    const state = bootstrapped();
    const newLedger = structuredClone(deltaFixture);
    newLedger.ledger_id = "ledger_22222222222222222222222222222222";
    const missingEvents = { ...page(deltaFixture), events: [] };

    const cases: Array<[() => unknown, string]> = [
      [
        () =>
          applyWorkSyncPage(state, page(deltaFixture), {
            gateway_id: "other-gateway",
            profile_id: scope.profile_id,
            after: 100,
          }),
        "identity_changed",
      ],
      [
        () =>
          applyWorkSyncPage(state, page(deltaFixture), {
            gateway_id: scope.gateway_id,
            profile_id: "profile_22222222222222222222222222222222",
            after: 100,
          }),
        "identity_changed",
      ],
      [
        () =>
          applyWorkSyncPage(state, page(newLedger), { ...scope, after: 100 }),
        "ledger_changed",
      ],
      [
        () =>
          applyWorkSyncPage(state, page(deltaFixture), { ...scope, after: 99 }),
        "cursor_invalid",
      ],
      [
        () =>
          applyWorkSyncPage(state, page(deltaFixture), {
            ...scope,
            after: 101,
          }),
        "cursor_invalid",
      ],
      [
        () => applyWorkSyncPage(state, missingEvents, { ...scope, after: 100 }),
        "cursor_invalid",
      ],
    ];
    for (const [operation, code] of cases) {
      try {
        operation();
        expect.fail("operation should fail closed");
      } catch (error) {
        expect(error).toBeInstanceOf(WorkSyncApplyError);
        expect((error as WorkSyncApplyError).code).toBe(code);
      }
    }
  });

  it("rejects first-event and internal delta gaps without advancing the cursor", () => {
    const state = bootstrapped();
    const firstGap = structuredClone(deltaFixture);
    firstGap.watermark = 102;
    firstGap.cursor = 102;
    firstGap.events[0]!.event_id = 102;

    const internalGap = structuredClone(tombstoneFixture);
    internalGap.watermark = 103;
    internalGap.cursor = 103;
    internalGap.events[0]!.event_id = 101;

    for (const candidate of [firstGap, internalGap]) {
      const before = structuredClone(state);
      expect(() =>
        applyWorkSyncPage(state, page(candidate), { ...scope, after: 100 }),
      ).toThrowError(
        expect.objectContaining<Partial<WorkSyncApplyError>>({
          code: "cursor_invalid",
        }),
      );
      expect(state).toEqual(before);
      expect(state.cursor).toBe(100);
    }
  });

  it("rejects a truncated delta page that cannot make cursor progress", () => {
    const state = applyWorkSyncPage(bootstrapped(), page(deltaFixture), {
      ...scope,
      after: 100,
    });
    const stalled = structuredClone(deltaFixture);
    stalled.watermark = 102;
    stalled.has_more = true;

    expect(() =>
      applyWorkSyncPage(state, page(stalled), { ...scope, after: 101 }),
    ).toThrowError(
      expect.objectContaining<Partial<WorkSyncApplyError>>({
        code: "cursor_invalid",
      }),
    );
    expect(state.cursor).toBe(101);
  });

  it("rejects a delta cursor beyond the final contiguous event", () => {
    const state = bootstrapped();
    const incomplete = structuredClone(page(deltaFixture));
    incomplete.watermark = 102;
    incomplete.cursor = 102;
    const before = structuredClone(state);

    expect(() =>
      applyWorkSyncPage(state, incomplete, { ...scope, after: 100 }),
    ).toThrowError(
      expect.objectContaining<Partial<WorkSyncApplyError>>({
        code: "cursor_invalid",
      }),
    );
    expect(state).toEqual(before);
    expect(state.cursor).toBe(100);
  });

  it("rejects a response bound to another profile before applying subjects", () => {
    const state = bootstrapped();
    const wrongProfile = structuredClone(page(deltaFixture));
    wrongProfile.work_profile_id = "profile_22222222222222222222222222222222";
    const before = structuredClone(state);

    expect(() =>
      applyWorkSyncPage(state, wrongProfile, { ...scope, after: 100 }),
    ).toThrowError(
      expect.objectContaining<Partial<WorkSyncApplyError>>({
        code: "identity_changed",
      }),
    );
    expect(state).toEqual(before);
  });

  it("applies a page atomically and leaves the prior cursor untouched on failure", () => {
    const state = bootstrapped();
    const poison = structuredClone(page(deltaFixture));
    poison.watermark = 102;
    poison.cursor = 102;
    poison.events = [
      poison.events[0]!,
      {
        ...poison.events[0]!,
        event_id: 102,
        subject_id: "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        subject_version: 99,
        subject: null,
      },
    ];
    const before = structuredClone(state);

    expect(() =>
      applyWorkSyncPage(state, poison, { ...scope, after: 100 }),
    ).toThrowError(
      expect.objectContaining<Partial<WorkSyncApplyError>>({
        code: "page_non_actionable",
      }),
    );
    expect(state).toEqual(before);
    expect(state.cursor).toBe(100);
    expect(state.jobs["job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]?.version).toBe(1);
  });

  it("discards the old namespace on cursor expiry and accepts only a new bootstrap", () => {
    const state = bootstrapped();
    const parsedReset = parseWorkCursorReset(replacedLedgerFixture);
    if (parsedReset.kind !== "verified") throw new Error("bad reset fixture");

    const reset = applyWorkCursorReset(state, parsedReset.reset, scope);
    expect(reset).toMatchObject({
      phase: "empty",
      ledger_id: null,
      cursor: null,
      reset_ledger_hint: "ledger_22222222222222222222222222222222",
      jobs: {},
      attention: {},
    });
    expect(() =>
      applyWorkSyncPage(reset, page(deltaFixture), { ...scope, after: 0 }),
    ).toThrowError(
      expect.objectContaining<Partial<WorkSyncApplyError>>({
        code: "bootstrap_required",
      }),
    );
  });
});
