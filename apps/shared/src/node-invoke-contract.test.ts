import { describe, expect, it } from "vitest";

import announceResultExcessFixture from "../../mobile/contracts/fabric-node-v1/announce-result-excess.json";
import announceResultUnroutableFixture from "../../mobile/contracts/fabric-node-v1/announce-result-unroutable.json";
import announceResultFixture from "../../mobile/contracts/fabric-node-v1/announce-result.json";
import invokeEventMalformedFixture from "../../mobile/contracts/fabric-node-v1/invoke-event-malformed.json";
import invokeEventFixture from "../../mobile/contracts/fabric-node-v1/invoke-event.json";
import manifest from "../../mobile/contracts/fabric-node-v1/manifest.json";
import receiptMismatchFixture from "../../mobile/contracts/fabric-node-v1/receipt-mismatch.json";
import receiptFixture from "../../mobile/contracts/fabric-node-v1/receipt.json";
import {
  NODE_GRANT_MAX_TTL_SECONDS,
  NODE_REJECT_REASONS,
  isNodeInvocationExpired,
  parseNodeAnnounceResult,
  parseNodeInvocation,
  validateNodeCapturedData,
  validateNodeReceipt,
  type NodeInvocation,
} from "./node-invoke-contract";

const ANNOUNCED = ["camera.capture", "photo.pick"] as const;
const INVOCATION_ID = "inv_9f8e7d6c5b4a39281706f5e4d3c2b1a0";

const announceFixtures: Record<string, unknown> = {
  "announce-result-excess.json": announceResultExcessFixture,
  "announce-result-unroutable.json": announceResultUnroutableFixture,
  "announce-result.json": announceResultFixture,
};

const invocationFixtures: Record<string, unknown> = {
  "invoke-event-malformed.json": invokeEventMalformedFixture,
  "invoke-event.json": invokeEventFixture,
};

const receiptFixtures: Record<string, unknown> = {
  "receipt-mismatch.json": receiptMismatchFixture,
  "receipt.json": receiptFixture,
};

function verifiedInvocation(value: unknown): NodeInvocation {
  const parsed = parseNodeInvocation(value);
  expect(parsed.kind).toBe("verified");
  if (parsed.kind !== "verified") throw new Error("fixture was not verified");
  return parsed.invocation;
}

function capturedData(overrides: Record<string, unknown> = {}): unknown {
  return {
    mime: "image/jpeg",
    bytes_b64: "aGVsbG8=",
    width: 2048,
    height: 1536,
    redactions: [{ kind: "face", region: [10, 20, 30, 40] }],
    ...overrides,
  };
}

describe("canonical fabric.node fixture corpus", () => {
  it("loads every manifest case through the reference parser", () => {
    expect(manifest).toMatchObject({
      name: "fabric.node.fixture-manifest",
      version: 1,
    });
    expect(new Set(manifest.cases.map((item) => item.id)).size).toBe(
      manifest.cases.length,
    );

    for (const fixtureCase of manifest.cases) {
      if (fixtureCase.kind === "announce") {
        const fixture = announceFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(
          parseNodeAnnounceResult(fixture, fixtureCase.announced ?? []).kind,
          fixtureCase.id,
        ).toBe(fixtureCase.expected);
      } else if (fixtureCase.kind === "invocation") {
        const fixture = invocationFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(parseNodeInvocation(fixture).kind, fixtureCase.id).toBe(
          fixtureCase.expected,
        );
      } else {
        const fixture = receiptFixtures[fixtureCase.file];
        expect(fixture, fixtureCase.file).toBeDefined();
        expect(
          validateNodeReceipt(fixture, fixtureCase.expected_invocation_id ?? "")
            .kind,
          fixtureCase.id,
        ).toBe(fixtureCase.expected);
      }
    }
    expect(
      Object.keys(announceFixtures).length +
        Object.keys(invocationFixtures).length +
        Object.keys(receiptFixtures).length,
    ).toBe(manifest.cases.length);
  });

  it("verifies an announce result whose sets nest correctly", () => {
    const parsed = parseNodeAnnounceResult(announceResultFixture, ANNOUNCED);
    expect(parsed).toEqual({
      kind: "verified",
      result: {
        accepted: ["camera.capture", "photo.pick"],
        node_token: "node-token-1a2b3c4d5e6f70819202a1b2c3d4e5f6",
        routable: ["camera.capture"],
      },
    });
  });

  it("fails closed when accepted exceeds the announced set", () => {
    expect(
      parseNodeAnnounceResult(announceResultExcessFixture, ANNOUNCED),
    ).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("accepted"),
    });
  });

  it("fails closed when routable exceeds the accepted set", () => {
    expect(
      parseNodeAnnounceResult(announceResultUnroutableFixture, ANNOUNCED),
    ).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("routable"),
    });
  });

  it("decodes the camera.capture invocation with epoch-millisecond expiry", () => {
    const invocation = verifiedInvocation(invokeEventFixture);
    expect(invocation).toMatchObject({
      invocation_id: INVOCATION_ID,
      session_id: "session-mobile-1",
      capability: "camera.capture",
      params: { facing: "rear", max_edge: 2048, allow_redaction: true },
    });
    expect(invocation.reason.length).toBeGreaterThan(0);
    expect(Number.isSafeInteger(invocation.expires_at)).toBe(true);
    // Unix epoch milliseconds, matching every fabric.work timestamp.
    expect(invocation.expires_at).toBeGreaterThan(1_000_000_000_000);
  });

  it("rejects the intentionally malformed invocation", () => {
    expect(parseNodeInvocation(invokeEventMalformedFixture)).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("expires_at"),
    });
  });

  it("accepts a receipt only when it echoes the expected invocation", () => {
    expect(validateNodeReceipt(receiptFixture, INVOCATION_ID)).toEqual({
      kind: "valid",
    });
    expect(
      validateNodeReceipt(receiptMismatchFixture, INVOCATION_ID),
    ).toMatchObject({
      kind: "invalid",
      message: expect.stringContaining("invocation_id"),
    });
  });
});

describe("node announce invariants", () => {
  it("rejects duplicate accepted entries", () => {
    expect(
      parseNodeAnnounceResult(
        {
          ...announceResultFixture,
          accepted: ["camera.capture", "camera.capture"],
        },
        ANNOUNCED,
      ),
    ).toMatchObject({ kind: "invalid" });
  });

  it("rejects duplicate routable entries", () => {
    expect(
      parseNodeAnnounceResult(
        {
          ...announceResultFixture,
          routable: ["camera.capture", "camera.capture"],
        },
        ANNOUNCED,
      ),
    ).toMatchObject({ kind: "invalid" });
  });

  it("rejects an empty or mistyped node_token", () => {
    expect(
      parseNodeAnnounceResult(
        { ...announceResultFixture, node_token: "" },
        ANNOUNCED,
      ),
    ).toMatchObject({ kind: "invalid" });
    expect(
      parseNodeAnnounceResult(
        { ...announceResultFixture, node_token: 7 },
        ANNOUNCED,
      ),
    ).toMatchObject({ kind: "invalid" });
  });

  it("requires every field, including empty capability sets, to be well typed", () => {
    for (const key of ["accepted", "node_token", "routable"]) {
      const clone: Record<string, unknown> = { ...announceResultFixture };
      delete clone[key];
      expect(parseNodeAnnounceResult(clone, ANNOUNCED), key).toMatchObject({
        kind: "invalid",
      });
    }
    expect(
      parseNodeAnnounceResult(
        { accepted: [], node_token: "node-token-1", routable: [] },
        ANNOUNCED,
      ),
    ).toMatchObject({ kind: "verified" });
  });
});

describe("invocation expiry and the grant ceiling", () => {
  it("treats expires_at as an exclusive epoch-millisecond deadline", () => {
    const invocation = verifiedInvocation(invokeEventFixture);
    expect(isNodeInvocationExpired(invocation, invocation.expires_at - 1)).toBe(
      false,
    );
    expect(isNodeInvocationExpired(invocation, invocation.expires_at)).toBe(
      true,
    );
    expect(isNodeInvocationExpired(invocation, invocation.expires_at + 1)).toBe(
      true,
    );
  });

  it("pins the reject-reason vocabulary and the 900-second grant ceiling", () => {
    expect(NODE_REJECT_REASONS).toEqual([
      "denied",
      "unsupported",
      "foreground_required",
      "grant_expired",
      "permission_denied",
      "capture_failed",
      "expired",
    ]);
    expect(NODE_GRANT_MAX_TTL_SECONDS).toBe(900);
  });

  it("requires every invocation field with strict types", () => {
    for (const key of [
      "invocation_id",
      "session_id",
      "capability",
      "reason",
      "params",
      "expires_at",
    ]) {
      const clone: Record<string, unknown> = { ...invokeEventFixture };
      delete clone[key];
      expect(parseNodeInvocation(clone), key).toMatchObject({
        kind: "invalid",
      });
    }
    expect(
      parseNodeInvocation({ ...invokeEventFixture, params: "rear" }),
    ).toMatchObject({ kind: "invalid" });
    expect(
      parseNodeInvocation({ ...invokeEventFixture, expires_at: 1784451660.5 }),
    ).toMatchObject({ kind: "invalid" });
  });
});

describe("receipt echo discipline", () => {
  it("rejects a receipt that is not accepted", () => {
    expect(
      validateNodeReceipt(
        { invocation_id: INVOCATION_ID, accepted: false },
        INVOCATION_ID,
      ),
    ).toMatchObject({ kind: "invalid" });
  });

  it("rejects a receipt missing either field", () => {
    expect(
      validateNodeReceipt({ accepted: true }, INVOCATION_ID),
    ).toMatchObject({ kind: "invalid" });
    expect(
      validateNodeReceipt({ invocation_id: INVOCATION_ID }, INVOCATION_ID),
    ).toMatchObject({ kind: "invalid" });
    expect(validateNodeReceipt(null, INVOCATION_ID)).toMatchObject({
      kind: "invalid",
    });
  });
});

describe("captured data validation", () => {
  it("accepts a well-formed bytes payload and a well-formed json payload", () => {
    expect(validateNodeCapturedData(capturedData())).toEqual({ kind: "valid" });
    expect(
      validateNodeCapturedData({
        mime: "application/json",
        json: { latitude: 37, longitude: -122 },
        redactions: [],
      }),
    ).toEqual({ kind: "valid" });
  });

  it("requires exactly one of bytes_b64 and json", () => {
    expect(
      validateNodeCapturedData(capturedData({ json: { extra: true } })),
    ).toMatchObject({ kind: "invalid" });
    const neither = capturedData();
    delete (neither as Record<string, unknown>).bytes_b64;
    expect(validateNodeCapturedData(neither)).toMatchObject({
      kind: "invalid",
    });
  });

  it("requires a non-empty mime and positive integer dimensions", () => {
    expect(validateNodeCapturedData(capturedData({ mime: "" }))).toMatchObject({
      kind: "invalid",
    });
    expect(validateNodeCapturedData(capturedData({ width: 0 }))).toMatchObject({
      kind: "invalid",
    });
    expect(
      validateNodeCapturedData(capturedData({ height: -1 })),
    ).toMatchObject({ kind: "invalid" });
    expect(
      validateNodeCapturedData(capturedData({ width: 2048.5 })),
    ).toMatchObject({ kind: "invalid" });
  });

  it("validates redactions and their optional non-negative regions", () => {
    expect(
      validateNodeCapturedData(capturedData({ redactions: [{ kind: "text" }] })),
    ).toEqual({ kind: "valid" });
    expect(
      validateNodeCapturedData(
        capturedData({ redactions: [{ kind: "face", region: [0, 0, 0, 0] }] }),
      ),
    ).toEqual({ kind: "valid" });
    expect(
      validateNodeCapturedData(
        capturedData({
          redactions: [{ kind: "face", region: [-1, 20, 30, 40] }],
        }),
      ),
    ).toMatchObject({ kind: "invalid" });
    expect(
      validateNodeCapturedData(
        capturedData({ redactions: [{ kind: "face", region: [10, 20, 30] }] }),
      ),
    ).toMatchObject({ kind: "invalid" });
    expect(
      validateNodeCapturedData(capturedData({ redactions: [{ kind: "" }] })),
    ).toMatchObject({ kind: "invalid" });
    const missingRedactions = capturedData();
    delete (missingRedactions as Record<string, unknown>).redactions;
    expect(validateNodeCapturedData(missingRedactions)).toMatchObject({
      kind: "invalid",
    });
    expect(validateNodeCapturedData("not an object")).toMatchObject({
      kind: "invalid",
    });
  });
});
