import { describe, expect, it } from "vitest";

import additiveFutureFixture from "../../mobile/contracts/fabric-work-v1/additive-future.json";
import bootstrapPage1Fixture from "../../mobile/contracts/fabric-work-v1/bootstrap-page-1.json";
import bootstrapPage2Fixture from "../../mobile/contracts/fabric-work-v1/bootstrap-page-2.json";
import cursorExpiredFixture from "../../mobile/contracts/fabric-work-v1/cursor-expired.json";
import deltaFixture from "../../mobile/contracts/fabric-work-v1/delta.json";
import incompatibleFixture from "../../mobile/contracts/fabric-work-v1/incompatible.json";
import malformedFixture from "../../mobile/contracts/fabric-work-v1/malformed.json";
import manifest from "../../mobile/contracts/fabric-work-v1/manifest.json";
import replacedLedgerFixture from "../../mobile/contracts/fabric-work-v1/replaced-ledger.json";
import sensitiveAttentionFixture from "../../mobile/contracts/fabric-work-v1/sensitive-attention.json";
import terminalFixture from "../../mobile/contracts/fabric-work-v1/terminal.json";
import tombstoneFixture from "../../mobile/contracts/fabric-work-v1/tombstone.json";
import {
  WORK_SYNC_MAX_BYTES,
  WORK_SYNC_MAX_ITEMS,
  displayWorkEnum,
  parseWorkCursorReset,
  parseWorkSyncPage,
  type WorkSyncPage,
} from "./work-contract";

const pageFixtures: Record<string, unknown> = {
  "additive-future.json": additiveFutureFixture,
  "bootstrap-page-1.json": bootstrapPage1Fixture,
  "bootstrap-page-2.json": bootstrapPage2Fixture,
  "delta.json": deltaFixture,
  "incompatible.json": incompatibleFixture,
  "malformed.json": malformedFixture,
  "sensitive-attention.json": sensitiveAttentionFixture,
  "terminal.json": terminalFixture,
  "tombstone.json": tombstoneFixture,
};

const resetFixtures: Record<string, unknown> = {
  "cursor-expired.json": cursorExpiredFixture,
  "replaced-ledger.json": replacedLedgerFixture,
};

function verifiedPage(value: unknown): WorkSyncPage {
  const parsed = parseWorkSyncPage(value);
  expect(parsed.kind).toBe("verified");
  if (parsed.kind !== "verified") throw new Error("fixture was not verified");
  return parsed.page;
}

describe("canonical fabric.work fixture corpus", () => {
  it("loads every manifest case through the reference parser", () => {
    expect(manifest).toMatchObject({
      name: "fabric.work.fixture-manifest",
      version: 1,
    });
    expect(new Set(manifest.cases.map((item) => item.id)).size).toBe(
      manifest.cases.length,
    );

    for (const fixtureCase of manifest.cases) {
      if (fixtureCase.kind === "page") {
        const fixture = pageFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(parseWorkSyncPage(fixture).kind, fixtureCase.id).toBe(
          fixtureCase.expected,
        );
      } else {
        const fixture = resetFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(parseWorkCursorReset(fixture).kind, fixtureCase.id).toBe(
          fixtureCase.expected,
        );
      }
    }
    expect(
      Object.keys(pageFixtures).length + Object.keys(resetFixtures).length,
    ).toBe(manifest.cases.length);
  });

  it("captures a fixed-watermark multi-page bootstrap with integer milliseconds", () => {
    const first = verifiedPage(bootstrapPage1Fixture);
    const second = verifiedPage(bootstrapPage2Fixture);

    expect(first).toMatchObject({
      mode: "bootstrap",
      ledger_id: "ledger_11111111111111111111111111111111",
      work_profile_id: "profile_11111111111111111111111111111111",
      watermark: 100,
      cursor: 100,
      has_more: true,
    });
    expect(first.next_page_token).toBeTypeOf("string");
    expect(second).toMatchObject({
      mode: "bootstrap",
      watermark: 100,
      cursor: 100,
      has_more: false,
      next_page_token: null,
    });
    for (const timestamp of [
      first.jobs[0]?.created_at,
      first.jobs[0]?.updated_at,
      first.attention[0]?.created_at,
    ]) {
      expect(Number.isSafeInteger(timestamp)).toBe(true);
    }
  });

  it("decodes complete delta after-states, tombstones, and terminal evidence", () => {
    const delta = verifiedPage(deltaFixture);
    const tombstone = verifiedPage(tombstoneFixture);
    const terminal = verifiedPage(terminalFixture);

    expect(delta.events[0]).toMatchObject({
      event_id: 101,
      subject_type: "job",
      subject_version: 2,
      tombstone: false,
      subject: { object_type: "job", status: "running", version: 2 },
    });
    expect(tombstone.events[0]).toMatchObject({
      subject_type: "attention",
      subject_version: 3,
      tombstone: true,
      subject: null,
    });
    expect(terminal.events[0]?.subject).toMatchObject({
      object_type: "job",
      status: "succeeded",
      result_preview: { text: "QA brief prepared" },
    });
  });

  it("keeps sensitive Attention free of response material", () => {
    const page = verifiedPage(sensitiveAttentionFixture);
    const subject = page.events[0]?.subject;
    expect(subject).toMatchObject({
      object_type: "attention",
      kind: "secret",
      sensitive: true,
      actionable: true,
    });
    expect(JSON.stringify(sensitiveAttentionFixture)).not.toMatch(
      /password|secret_value|raw_response|response_value/i,
    );
    if (subject?.object_type === "attention") {
      expect(Object.keys(subject)).not.toContain("value");
      expect(Object.keys(subject)).not.toContain("response");
    }
  });

  it("accepts additive future fields and preserves unknown enums as non-actionable", () => {
    const page = verifiedPage(additiveFutureFixture);
    const job = page.jobs[0];

    expect(page.contract).toEqual({
      name: "fabric.work",
      version: 2,
      min_compatible: 1,
    });
    expect(page.actionable).toBe(true);
    expect(job).toMatchObject({
      kind: "future_workflow",
      status: "materializing",
      actionable: false,
    });
    expect(job?.unknown_enums.map((entry) => entry.raw)).toEqual([
      "future_workflow",
      "materializing",
    ]);
    expect(displayWorkEnum(job?.status ?? "", ["queued", "running"])).toBe(
      "unknown(materializing)",
    );
    expect(page).not.toHaveProperty("future_page_field");
    expect(job).not.toHaveProperty("future_job_field");
  });

  it("preserves future Attention enums without authorizing their actions", () => {
    const future = structuredClone(sensitiveAttentionFixture);
    future.contract.version = 2;
    future.events[0]!.subject!.state = "awaiting_biometric";
    future.events[0]!.subject!.allowed_actions = ["confirm_biometric"];
    const subject = verifiedPage(future).events[0]?.subject;

    expect(subject).toMatchObject({
      object_type: "attention",
      state: "awaiting_biometric",
      allowed_actions: ["confirm_biometric"],
      actionable: false,
    });
    if (subject?.object_type === "attention") {
      expect(subject.unknown_enums.map((entry) => entry.raw)).toEqual([
        "awaiting_biometric",
        "confirm_biometric",
      ]);
    }
  });

  it("preserves a constrained known Attention action subset as authoritative", () => {
    const constrained = structuredClone(sensitiveAttentionFixture);
    constrained.events[0]!.subject!.allowed_actions = ["cancel"];
    const subject = verifiedPage(constrained).events[0]?.subject;

    expect(subject).toMatchObject({
      object_type: "attention",
      allowed_actions: ["cancel"],
      actionable: true,
    });
  });

  it("fails closed when the minimum compatible version exceeds v1", () => {
    expect(parseWorkSyncPage(incompatibleFixture)).toEqual({
      kind: "incompatible",
      minimum: 2,
    });
  });

  it("requires every nullable field to be present rather than treating omission as null", () => {
    const deletions: Array<[unknown, string[]]> = [
      [
        bootstrapPage1Fixture,
        [
          "summary",
          "source_session_key",
          "runtime_session_id",
          "started_at",
          "finished_at",
          "cancel_requested_at",
          "current_run",
          "result_preview",
          "result_ref",
          "result_omitted_reason",
          "error",
        ],
      ],
      [
        (bootstrapPage1Fixture.jobs[0] as { current_run: unknown }).current_run,
        ["claimed_at", "started_at", "finished_at"],
      ],
      [
        bootstrapPage1Fixture.attention[0],
        [
          "job_id",
          "run_id",
          "source_session_key",
          "runtime_session_id",
          "expires_at",
          "resolved_at",
          "terminal_reason",
        ],
      ],
      [deltaFixture.events[0], ["job_id", "run_id", "subject"]],
    ];

    for (const [target, fields] of deletions) {
      for (const field of fields) {
        const fixture = structuredClone(bootstrapPage1Fixture) as Record<
          string,
          unknown
        >;
        const jobs = fixture.jobs as Array<Record<string, unknown>>;
        const attention = fixture.attention as Array<Record<string, unknown>>;
        let cloneTarget: Record<string, unknown>;
        if (target === bootstrapPage1Fixture) cloneTarget = jobs[0]!;
        else if (target === bootstrapPage1Fixture.attention[0]) {
          cloneTarget = attention[0]!;
        } else if (target === deltaFixture.events[0]) {
          const deltaClone = structuredClone(deltaFixture) as Record<
            string,
            unknown
          >;
          cloneTarget = (
            deltaClone.events as Array<Record<string, unknown>>
          )[0]!;
          delete cloneTarget[field];
          expect(parseWorkSyncPage(deltaClone), field).toMatchObject({
            kind: "invalid",
          });
          continue;
        } else {
          cloneTarget = jobs[0]!.current_run as Record<string, unknown>;
        }
        delete cloneTarget[field];
        expect(parseWorkSyncPage(fixture), field).toMatchObject({
          kind: "invalid",
        });
      }
    }

    const withoutPageNull = structuredClone(bootstrapPage2Fixture) as Record<
      string,
      unknown
    >;
    delete withoutPageNull.next_page_token;
    expect(parseWorkSyncPage(withoutPageNull)).toMatchObject({
      kind: "invalid",
    });
  });

  it("requires an opaque profile binding on every compatible sync page", () => {
    const missing = structuredClone(deltaFixture) as Record<string, unknown>;
    delete missing.work_profile_id;
    expect(parseWorkSyncPage(missing)).toMatchObject({ kind: "invalid" });

    expect(
      parseWorkSyncPage({
        ...deltaFixture,
        work_profile_id: "default",
      }),
    ).toMatchObject({ kind: "invalid" });
  });

  it("rejects fractional timestamps and the intentionally malformed fixture", () => {
    expect(parseWorkSyncPage(malformedFixture)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("finished_at"),
    });
    const fractional = structuredClone(bootstrapPage2Fixture);
    fractional.jobs[0]!.updated_at += 0.5;
    expect(parseWorkSyncPage(fractional)).toMatchObject({ kind: "invalid" });
  });

  it("enforces the one-MiB page, 500-item, and preview byte limits", () => {
    expect(
      parseWorkSyncPage(bootstrapPage2Fixture, {
        encodedBytes: WORK_SYNC_MAX_BYTES + 1,
      }),
    ).toMatchObject({ kind: "invalid" });

    const oversizedPreview = structuredClone(terminalFixture);
    const subject = oversizedPreview.events[0]!.subject as Record<
      string,
      unknown
    >;
    subject.result_preview = "x".repeat(4097);
    expect(parseWorkSyncPage(oversizedPreview)).toMatchObject({
      kind: "invalid",
    });

    const tooMany = structuredClone(tombstoneFixture) as Record<
      string,
      unknown
    >;
    const base = (tooMany.events as Array<Record<string, unknown>>)[0]!;
    tooMany.events = Array.from(
      { length: WORK_SYNC_MAX_ITEMS + 1 },
      (_, index) => ({
        ...base,
        event_id: index + 1,
        subject_version: index + 1,
      }),
    );
    tooMany.cursor = WORK_SYNC_MAX_ITEMS + 1;
    tooMany.watermark = WORK_SYNC_MAX_ITEMS + 1;
    expect(parseWorkSyncPage(tooMany)).toMatchObject({ kind: "invalid" });
  });

  it("parses sanitized replaced-ledger and retained-floor reset instructions", () => {
    expect(parseWorkCursorReset(replacedLedgerFixture)).toMatchObject({
      kind: "verified",
      reset: {
        data: {
          code: "cursor_expired",
          bootstrap: true,
          reason: "ledger_replaced",
          ledger_id: "ledger_22222222222222222222222222222222",
        },
      },
    });
    expect(parseWorkCursorReset(cursorExpiredFixture)).toMatchObject({
      kind: "verified",
      reset: {
        data: { reason: "retention_floor", event_floor: 80, high_water: 105 },
      },
    });
    expect(
      parseWorkCursorReset({ ...cursorExpiredFixture, code: -32048 }),
    ).toEqual({
      kind: "invalid",
      message: "work reset.code must be -32047.",
    });
  });
});
