import { describe, expect, it } from "vitest";

import auditPage1Fixture from "../../mobile/contracts/fabric-trust-v1/audit-page-1.json";
import auditPage2Fixture from "../../mobile/contracts/fabric-trust-v1/audit-page-2.json";
import auditUnknownKindFixture from "../../mobile/contracts/fabric-trust-v1/audit-unknown-kind.json";
import auditUnredactedFixture from "../../mobile/contracts/fabric-trust-v1/audit-unredacted.json";
import cursorExpiredFixture from "../../mobile/contracts/fabric-trust-v1/cursor-expired.json";
import grantRevokeReceiptFixture from "../../mobile/contracts/fabric-trust-v1/grant-revoke-receipt.json";
import grantsFixture from "../../mobile/contracts/fabric-trust-v1/grants.json";
import malformedFixture from "../../mobile/contracts/fabric-trust-v1/malformed.json";
import manifest from "../../mobile/contracts/fabric-trust-v1/manifest.json";
import scopedGrantReceiptFixture from "../../mobile/contracts/fabric-trust-v1/scoped-grant-receipt.json";
import {
  TRUST_AUDIT_ACTORS,
  TRUST_AUDIT_DECISIONS,
  TRUST_AUDIT_KINDS,
  TRUST_AUDIT_LIST_MAX_ENTRIES,
  TRUST_AUDIT_SUMMARY_MAX_CHARS,
  TRUST_CLIENT_CONTRACT_VERSION,
  TRUST_GRANT_SCOPES,
  TRUST_GRANT_SOURCES,
  isTrustGrantActionable,
  parseGrantRevokeReceipt,
  parseScopedGrantReceipt,
  parseTrustAuditPage,
  parseTrustCursorReset,
  parseTrustGrantList,
  type TrustAuditPage,
  type TrustGrant,
} from "./trust-contract";

const REVOKE_EXPECTATION = {
  grantId: "grant-22222222",
  expectedVersion: 3,
} as const;

const pageFixtures: Record<string, unknown> = {
  "audit-page-1.json": auditPage1Fixture,
  "audit-page-2.json": auditPage2Fixture,
  "audit-unknown-kind.json": auditUnknownKindFixture,
  "audit-unredacted.json": auditUnredactedFixture,
  "malformed.json": malformedFixture,
};

const grantsFixtures: Record<string, unknown> = {
  "grants.json": grantsFixture,
};

const revokeReceiptFixtures: Record<string, unknown> = {
  "grant-revoke-receipt.json": grantRevokeReceiptFixture,
};

const scopedReceiptFixtures: Record<string, unknown> = {
  "scoped-grant-receipt.json": scopedGrantReceiptFixture,
};

const resetFixtures: Record<string, unknown> = {
  "cursor-expired.json": cursorExpiredFixture,
};

function verifiedPage(value: unknown): TrustAuditPage {
  const parsed = parseTrustAuditPage(value);
  expect(parsed.kind).toBe("verified");
  if (parsed.kind !== "verified") throw new Error("fixture was not verified");
  return parsed.page;
}

function verifiedGrants(value: unknown): readonly TrustGrant[] {
  const parsed = parseTrustGrantList(value);
  expect(parsed.kind).toBe("verified");
  if (parsed.kind !== "verified") throw new Error("fixture was not verified");
  return parsed.grants;
}

describe("canonical fabric.trust fixture corpus", () => {
  it("loads every manifest case through the reference parser", () => {
    expect(manifest).toMatchObject({
      name: "fabric.trust.fixture-manifest",
      version: 1,
    });
    expect(new Set(manifest.cases.map((item) => item.id)).size).toBe(
      manifest.cases.length,
    );

    for (const fixtureCase of manifest.cases) {
      if (fixtureCase.kind === "page") {
        const fixture = pageFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(parseTrustAuditPage(fixture).kind, fixtureCase.id).toBe(
          fixtureCase.expected,
        );
      } else if (fixtureCase.kind === "grants") {
        const fixture = grantsFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(parseTrustGrantList(fixture).kind, fixtureCase.id).toBe(
          fixtureCase.expected,
        );
      } else if (fixtureCase.kind === "revoke_receipt") {
        const fixture = revokeReceiptFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(
          parseGrantRevokeReceipt(fixture, REVOKE_EXPECTATION).kind,
          fixtureCase.id,
        ).toBe(fixtureCase.expected);
      } else if (fixtureCase.kind === "scoped_receipt") {
        const fixture = scopedReceiptFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(parseScopedGrantReceipt(fixture).kind, fixtureCase.id).toBe(
          fixtureCase.expected,
        );
      } else {
        const fixture = resetFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(parseTrustCursorReset(fixture).kind, fixtureCase.id).toBe(
          fixtureCase.expected,
        );
      }
    }
    expect(
      Object.keys(pageFixtures).length +
        Object.keys(grantsFixtures).length +
        Object.keys(revokeReceiptFixtures).length +
        Object.keys(scopedReceiptFixtures).length +
        Object.keys(resetFixtures).length,
    ).toBe(manifest.cases.length);
  });

  it("pins the version-1 enum vocabulary", () => {
    expect(TRUST_CLIENT_CONTRACT_VERSION).toBe(1);
    expect(TRUST_AUDIT_LIST_MAX_ENTRIES).toBe(200);
    expect(TRUST_AUDIT_SUMMARY_MAX_CHARS).toBe(512);
    expect(TRUST_AUDIT_ACTORS).toEqual(["agent", "user", "system"]);
    expect(TRUST_AUDIT_KINDS).toEqual([
      "capability_invocation",
      "approval",
      "grant_change",
      "node_change",
      "auth",
    ]);
    expect(TRUST_AUDIT_DECISIONS).toEqual(["allowed", "denied", "auto"]);
    expect(TRUST_GRANT_SCOPES).toEqual(["session", "always", "scoped"]);
    expect(TRUST_GRANT_SOURCES).toEqual(["mobile", "desktop", "cli"]);
  });

  it("captures a cursor continuation across two audit pages", () => {
    const first = verifiedPage(auditPage1Fixture);
    const second = verifiedPage(auditPage2Fixture);

    expect(first).toMatchObject({
      cursor: 205,
      next_before: 201,
      actionable: true,
    });
    expect(second).toMatchObject({
      cursor: 205,
      next_before: null,
      actionable: true,
    });
    for (const page of [first, second]) {
      let prior = 0;
      for (const entry of page.entries) {
        expect(entry.entry_id).toBeGreaterThan(prior);
        expect(entry.redacted).toBe(true);
        expect(Number.isSafeInteger(entry.at)).toBe(true);
        prior = entry.entry_id;
      }
    }
    expect(second.entries.at(-1)!.entry_id).toBeLessThan(
      first.entries[0]!.entry_id,
    );
  });

  it("accepts an empty entries page and preserves optional entry fields as null", () => {
    const page = verifiedPage({
      contract: { name: "fabric.trust", version: 1, min_compatible: 1 },
      cursor: 0,
      entries: [],
    });
    expect(page.entries).toEqual([]);
    expect(page.next_before).toBeNull();

    const enrollment = verifiedPage(auditPage1Fixture).entries.find(
      (entry) => entry.kind === "auth",
    );
    expect(enrollment).toMatchObject({
      session_id: null,
      session_title: null,
      grant_id: null,
      decision: null,
      node_id: "node-phone-1",
    });
  });

  it("preserves a future audit kind as visible but non-actionable", () => {
    const page = verifiedPage(auditUnknownKindFixture);
    const future = page.entries.find((entry) => entry.kind === "biometric_check");
    expect(future).toMatchObject({ actionable: false, redacted: true });
    expect(future?.unknown_enums.map((entry) => entry.raw)).toEqual([
      "biometric_check",
    ]);
    expect(page.actionable).toBe(false);
    const known = page.entries.find((entry) => entry.kind === "approval");
    expect(known?.actionable).toBe(true);
  });

  it("rejects any entry that is not server-redacted", () => {
    expect(parseTrustAuditPage(auditUnredactedFixture)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("redacted"),
    });
    const literalTrue = structuredClone(auditPage1Fixture) as Record<
      string,
      unknown
    >;
    (literalTrue.entries as Array<Record<string, unknown>>)[0]!.redacted =
      "true";
    expect(parseTrustAuditPage(literalTrue)).toMatchObject({
      kind: "invalid",
    });
  });

  it("rejects the malformed fixture and out-of-order or oversized entries", () => {
    expect(parseTrustAuditPage(malformedFixture)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("summary"),
    });

    const decreasing = structuredClone(auditPage1Fixture) as Record<
      string,
      unknown
    >;
    const entries = decreasing.entries as Array<Record<string, unknown>>;
    entries[1]!.entry_id = 200;
    expect(parseTrustAuditPage(decreasing)).toMatchObject({ kind: "invalid" });

    const duplicated = structuredClone(auditPage1Fixture) as Record<
      string,
      unknown
    >;
    (duplicated.entries as Array<Record<string, unknown>>)[1]!.entry_id = 201;
    expect(parseTrustAuditPage(duplicated)).toMatchObject({ kind: "invalid" });

    const oversized = structuredClone(auditPage1Fixture) as Record<
      string,
      unknown
    >;
    (oversized.entries as Array<Record<string, unknown>>)[0]!.summary =
      "x".repeat(TRUST_AUDIT_SUMMARY_MAX_CHARS + 1);
    expect(parseTrustAuditPage(oversized)).toMatchObject({ kind: "invalid" });

    const tooMany = structuredClone(auditPage1Fixture) as Record<
      string,
      unknown
    >;
    const base = (tooMany.entries as Array<Record<string, unknown>>)[0]!;
    tooMany.entries = Array.from(
      { length: TRUST_AUDIT_LIST_MAX_ENTRIES + 1 },
      (_, index) => ({ ...base, entry_id: index + 1 }),
    );
    expect(parseTrustAuditPage(tooMany)).toMatchObject({ kind: "invalid" });
  });

  it("fails closed when the minimum compatible version exceeds v1", () => {
    const future = structuredClone(auditPage1Fixture) as Record<
      string,
      unknown
    >;
    future.contract = { name: "fabric.trust", version: 2, min_compatible: 2 };
    expect(parseTrustAuditPage(future)).toEqual({
      kind: "incompatible",
      minimum: 2,
    });
  });

  it("decodes revocable, non-revocable, and unknown-scope grants", () => {
    const grants = verifiedGrants(grantsFixture);
    expect(grants).toHaveLength(3);

    const scoped = grants.find((grant) => grant.grant_id === "grant-11111111");
    expect(scoped).toMatchObject({
      capability: "camera.capture",
      scope: "scoped",
      revocable: true,
      actionable: true,
    });
    expect(isTrustGrantActionable(scoped!)).toBe(true);

    const locked = grants.find((grant) => grant.grant_id === "grant-22222222");
    expect(locked).toMatchObject({ revocable: false, actionable: true });
    expect(isTrustGrantActionable(locked!)).toBe(true);

    const unknownScope = grants.find(
      (grant) => grant.grant_id === "grant-33333333",
    );
    expect(unknownScope).toMatchObject({
      scope: "geo_fenced",
      actionable: false,
    });
    expect(unknownScope?.unknown_enums.map((entry) => entry.raw)).toEqual([
      "geo_fenced",
    ]);
    expect(isTrustGrantActionable(unknownScope!)).toBe(false);
  });

  it("keeps an unknown grant source visible but non-actionable", () => {
    const mutated = structuredClone(grantsFixture) as Record<string, unknown>;
    (mutated.grants as Array<Record<string, unknown>>)[0]!.source = "watch";
    const grants = verifiedGrants(mutated);
    expect(grants[0]).toMatchObject({ source: "watch", actionable: false });
    expect(isTrustGrantActionable(grants[0]!)).toBe(false);
  });

  it("rejects grant lists with duplicate ids or mistyped fields", () => {
    const duplicated = structuredClone(grantsFixture) as Record<
      string,
      unknown
    >;
    const grants = duplicated.grants as Array<Record<string, unknown>>;
    grants[1]!.grant_id = grants[0]!.grant_id;
    expect(parseTrustGrantList(duplicated)).toMatchObject({ kind: "invalid" });

    const fractional = structuredClone(grantsFixture) as Record<
      string,
      unknown
    >;
    (fractional.grants as Array<Record<string, unknown>>)[0]!.use_count = 1.5;
    expect(parseTrustGrantList(fractional)).toMatchObject({ kind: "invalid" });
  });

  it("verifies a revoke receipt only when it echoes the mutation faithfully", () => {
    expect(
      parseGrantRevokeReceipt(grantRevokeReceiptFixture, REVOKE_EXPECTATION),
    ).toEqual({
      kind: "verified",
      receipt: {
        grant_id: "grant-22222222",
        revoked: true,
        revoked_at: 1784452000000,
        grant_version: 4,
        mutation_id: "mut-7c9a1f2b",
        replayed: false,
      },
    });

    expect(
      parseGrantRevokeReceipt(grantRevokeReceiptFixture, {
        grantId: "grant-99999999",
        expectedVersion: 3,
      }),
    ).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("grant_id"),
    });

    expect(
      parseGrantRevokeReceipt(grantRevokeReceiptFixture, {
        grantId: "grant-22222222",
        expectedVersion: 4,
      }),
    ).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("grant_version"),
    });

    const missingMutation = structuredClone(grantRevokeReceiptFixture) as Record<
      string,
      unknown
    >;
    delete missingMutation.mutation_id;
    expect(
      parseGrantRevokeReceipt(missingMutation, REVOKE_EXPECTATION),
    ).toMatchObject({ kind: "invalid" });

    const emptyMutation = { ...grantRevokeReceiptFixture, mutation_id: "" };
    expect(
      parseGrantRevokeReceipt(emptyMutation, REVOKE_EXPECTATION),
    ).toMatchObject({ kind: "invalid" });
  });

  it("treats a scoped-grant receipt without grant_id as none, never an error", () => {
    expect(parseScopedGrantReceipt(scopedGrantReceiptFixture)).toEqual({
      kind: "verified",
      receipt: { grant_id: "grant-44444444", expires_at: 1784455200000 },
    });

    expect(
      parseScopedGrantReceipt({ request_id: "req-approve-1", resolved: true }),
    ).toEqual({ kind: "none" });

    expect(
      parseScopedGrantReceipt({ ...scopedGrantReceiptFixture, grant_id: "" }),
    ).toMatchObject({ kind: "invalid" });
    expect(
      parseScopedGrantReceipt({
        request_id: "req-approve-1",
        grant_id: "grant-55555555",
      }),
    ).toEqual({
      kind: "verified",
      receipt: { grant_id: "grant-55555555", expires_at: null },
    });
    expect(parseScopedGrantReceipt(null)).toMatchObject({ kind: "invalid" });
  });

  it("parses the sanitized cursor_expired reset instruction", () => {
    expect(parseTrustCursorReset(cursorExpiredFixture)).toMatchObject({
      kind: "verified",
      reset: {
        code: -32047,
        data: {
          code: "cursor_expired",
          bootstrap: true,
          reason: "retention_floor",
          event_floor: 150,
          high_water: 205,
        },
      },
    });
    expect(
      parseTrustCursorReset({ ...cursorExpiredFixture, code: -32048 }),
    ).toEqual({
      kind: "invalid",
      message: "trust reset.code must be -32047.",
    });
    const wrongDataCode = structuredClone(cursorExpiredFixture) as {
      data: Record<string, unknown>;
    };
    wrongDataCode.data.code = "ledger_replaced";
    expect(parseTrustCursorReset(wrongDataCode)).toMatchObject({
      kind: "invalid",
    });
  });
});
