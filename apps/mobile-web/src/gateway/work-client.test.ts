import {
  GatewayRpcError,
  applyWorkSyncPage,
  createWorkProjection,
  parseGatewayCapabilities,
  parseWorkSyncPage,
  type GatewayCapabilities,
  type WorkProjection,
  type WorkSyncPage,
  type WorkSyncScope,
} from "@fabric/shared";
import { describe, expect, it, vi } from "vitest";

import gatewayFixture from "../../../mobile/contracts/gateway-capabilities-v1.json";
import bootstrapPage1Fixture from "../../../mobile/contracts/fabric-work-v1/bootstrap-page-1.json";
import bootstrapPage2Fixture from "../../../mobile/contracts/fabric-work-v1/bootstrap-page-2.json";
import deltaFixture from "../../../mobile/contracts/fabric-work-v1/delta.json";
import malformedFixture from "../../../mobile/contracts/fabric-work-v1/malformed.json";
import replacedLedgerFixture from "../../../mobile/contracts/fabric-work-v1/replaced-ledger.json";
import sensitiveAttentionFixture from "../../../mobile/contracts/fabric-work-v1/sensitive-attention.json";
import {
  FabricWorkRpc,
  WorkContractInvalidError,
  advertisedWorkProtocol,
  createBackgroundMutation,
  submitBackgroundMutation,
  synchronizeWorkProjection,
  type WorkGatewayRequest,
} from "./work-client";

const scope: WorkSyncScope = {
  gateway_id: "https://gateway.test",
  profile_id: "profile_11111111111111111111111111111111",
};

function parsedPage(value: unknown): WorkSyncPage {
  const parsed = parseWorkSyncPage(value);
  if (parsed.kind !== "verified") {
    throw new Error(`fixture did not parse: ${parsed.kind}`);
  }
  return parsed.page;
}

function asGatewayRequest(value: unknown): WorkGatewayRequest {
  return value as WorkGatewayRequest;
}

function durableCapabilities(): GatewayCapabilities {
  const raw = structuredClone(gatewayFixture) as Record<string, unknown>;
  const features = raw.features as Record<string, unknown>;
  const methods = raw.methods as string[];
  features.durable_work = true;
  methods.push(
    "job.create",
    "job.sync",
    "job.get",
    "job.list",
    "job.events",
    "job.cancel",
    "attention.get",
    "attention.list",
    "attention.respond",
  );
  const parsed = parseGatewayCapabilities(raw);
  if (parsed.kind !== "verified")
    throw new Error("capability fixture is invalid");
  return parsed.capabilities;
}

function bootstrappedProjection(): WorkProjection {
  const first = parsedPage(bootstrapPage1Fixture);
  const second = parsedPage(bootstrapPage2Fixture);
  const partial = applyWorkSyncPage(createWorkProjection(scope), first, {
    ...scope,
    page_token: null,
  });
  return applyWorkSyncPage(partial, second, {
    ...scope,
    page_token: first.next_page_token,
  });
}

describe("PWA durable Work protocol selection", () => {
  it("uses durable Work only when the compatible feature and complete methods are advertised", () => {
    expect(
      advertisedWorkProtocol({
        kind: "verified",
        capabilities: durableCapabilities(),
      }),
    ).toBe("durable");

    const oldGateway = parseGatewayCapabilities(gatewayFixture);
    expect(advertisedWorkProtocol(oldGateway)).toBe("legacy");
    expect(advertisedWorkProtocol({ kind: "legacy" })).toBe("legacy");
    expect(advertisedWorkProtocol({ kind: "incompatible", minimum: 2 })).toBe(
      "unavailable",
    );
  });

  it("reuses one idempotency key across a timeout and retry", async () => {
    const mutation = createBackgroundMutation(scope, "Review the release", {
      createIdempotencyKey: () => "11111111-1111-4111-8111-111111111111",
    });
    const params: Record<string, unknown>[] = [];
    let attempt = 0;
    const request = vi.fn(async (_method, nextParams) => {
      params.push(nextParams ?? {});
      attempt += 1;
      if (attempt === 1) {
        throw new GatewayRpcError("timeout", "request timed out: job.create");
      }
      return {
        job: {
          job_id: "job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          kind: "background_prompt",
          title: "Background work",
          version: 1,
        },
        mutation_id: "mutation-1",
        replayed: true,
      };
    });

    await expect(
      submitBackgroundMutation({
        mutation,
        protocol: "durable",
        request: asGatewayRequest(request),
        sessionId: "runtime-1",
      }),
    ).rejects.toMatchObject({ kind: "timeout" });
    await submitBackgroundMutation({
      mutation,
      protocol: "durable",
      request: asGatewayRequest(request),
      sessionId: "runtime-2",
    });

    expect(params).toHaveLength(2);
    expect(params[0]?.idempotency_key).toBe(mutation.idempotency_key);
    expect(params[1]?.idempotency_key).toBe(mutation.idempotency_key);
  });

  it("never falls back to prompt.background after a durable RPC error", async () => {
    const methods: string[] = [];
    const request = vi.fn(async (method) => {
      methods.push(method);
      throw new GatewayRpcError("rpc", "work store unavailable", {
        code: -32048,
      });
    });

    await expect(
      submitBackgroundMutation({
        mutation: createBackgroundMutation(scope, "Do the durable thing", {
          createIdempotencyKey: () => "22222222-2222-4222-8222-222222222222",
        }),
        protocol: "durable",
        request: asGatewayRequest(request),
        sessionId: "runtime-1",
      }),
    ).rejects.toMatchObject({ code: -32048 });
    expect(methods).toEqual(["job.create"]);
  });
});

describe("PWA Work projection synchronization", () => {
  it("applies every bootstrap page before exposing its cursor, then catches up by delta", async () => {
    const responses = [
      bootstrapPage1Fixture,
      bootstrapPage2Fixture,
      deltaFixture,
    ];
    const request = vi.fn(async () => responses.shift());
    const commits: WorkProjection[] = [];

    const result = await synchronizeWorkProjection({
      commit: ({ projection }) => commits.push(projection),
      initial: createWorkProjection(scope),
      isCurrent: () => true,
      rpc: new FabricWorkRpc(asGatewayRequest(request)),
      scope,
      sessionId: "runtime-1",
    });

    expect(result.kind).toBe("current");
    expect(commits.map((projection) => projection.cursor)).toEqual([
      null,
      null,
      100,
      101,
    ]);
    expect(commits[1]?.phase).toBe("bootstrapping");
    expect(
      commits.at(-1)?.jobs.job_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,
    ).toMatchObject({ status: "running", version: 2 });
  });

  it("keeps the last committed bootstrap page and no cursor when a later page is invalid", async () => {
    const responses = [bootstrapPage1Fixture, malformedFixture];
    const commits: WorkProjection[] = [];

    await expect(
      synchronizeWorkProjection({
        commit: ({ projection }) => commits.push(projection),
        initial: createWorkProjection(scope),
        isCurrent: () => true,
        rpc: new FabricWorkRpc(
          asGatewayRequest(vi.fn(async () => responses.shift())),
        ),
        scope,
        sessionId: "runtime-1",
      }),
    ).rejects.toBeInstanceOf(WorkContractInvalidError);

    const lastCommitted = commits.at(-1);
    expect(lastCommitted).toMatchObject({
      cursor: null,
      phase: "bootstrapping",
    });
    expect(
      lastCommitted?.jobs.job_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,
    ).toMatchObject({ version: 4 });
  });

  it("fails closed when bootstrap repeats a continuation token", async () => {
    const repeated = structuredClone(bootstrapPage1Fixture);
    const responses = [bootstrapPage1Fixture, repeated];
    const commits: WorkProjection[] = [];

    await expect(
      synchronizeWorkProjection({
        commit: ({ projection }) => commits.push(projection),
        initial: createWorkProjection(scope),
        isCurrent: () => true,
        rpc: new FabricWorkRpc(
          asGatewayRequest(vi.fn(async () => responses.shift())),
        ),
        scope,
        sessionId: "runtime-1",
      }),
    ).rejects.toThrow(/repeated a bootstrap page token/);

    expect(commits).toHaveLength(2);
    expect(commits.at(-1)).toMatchObject({
      cursor: null,
      phase: "bootstrapping",
    });
  });

  it("does not commit a response from a stale connection generation", async () => {
    let release!: (value: unknown) => void;
    const response = new Promise<unknown>((resolve) => {
      release = resolve;
    });
    const request = vi.fn(async () => response);
    let current = true;
    const commits: WorkProjection[] = [];
    const syncing = synchronizeWorkProjection({
      commit: ({ projection }) => commits.push(projection),
      initial: createWorkProjection(scope),
      isCurrent: () => current,
      rpc: new FabricWorkRpc(asGatewayRequest(request)),
      scope,
      sessionId: "runtime-1",
    });
    expect(commits).toHaveLength(1);

    current = false;
    release(bootstrapPage1Fixture);
    await expect(syncing).resolves.toMatchObject({ kind: "stale" });
    expect(commits).toHaveLength(1);
    expect(commits[0]?.cursor).toBeNull();
  });

  it.each([
    [{ gateway_id: "https://other.test", profile_id: scope.profile_id }],
    [
      {
        gateway_id: scope.gateway_id,
        profile_id: "profile_22222222222222222222222222222222",
      },
    ],
  ])(
    "replaces state before syncing a changed gateway/profile identity",
    async (nextScope) => {
      const responses = [
        structuredClone(bootstrapPage1Fixture),
        structuredClone(bootstrapPage2Fixture),
        structuredClone(deltaFixture),
      ];
      for (const response of responses) {
        response.work_profile_id = nextScope.profile_id;
      }
      const commits: WorkProjection[] = [];
      await synchronizeWorkProjection({
        commit: ({ projection }) => commits.push(projection),
        initial: bootstrappedProjection(),
        isCurrent: () => true,
        rpc: new FabricWorkRpc(
          asGatewayRequest(vi.fn(async () => responses.shift())),
        ),
        scope: nextScope,
        sessionId: "runtime-2",
      });

      expect(commits[0]).toMatchObject({
        ...nextScope,
        cursor: null,
        ledger_id: null,
        jobs: {},
        attention: {},
      });
    },
  );

  it("discards the old ledger on cursor reset before bootstrapping its replacement", async () => {
    const replacementOne = structuredClone(bootstrapPage1Fixture);
    const replacementTwo = structuredClone(bootstrapPage2Fixture);
    const replacementDelta = structuredClone(deltaFixture);
    for (const page of [replacementOne, replacementTwo, replacementDelta]) {
      page.ledger_id = replacedLedgerFixture.data.ledger_id;
    }
    let requestCount = 0;
    const request = vi.fn(async () => {
      requestCount += 1;
      if (requestCount === 1) {
        throw new GatewayRpcError("rpc", replacedLedgerFixture.message, {
          code: replacedLedgerFixture.code,
          data: replacedLedgerFixture.data,
        });
      }
      return [replacementOne, replacementTwo, replacementDelta][
        requestCount - 2
      ];
    });
    const commits: WorkProjection[] = [];

    const result = await synchronizeWorkProjection({
      commit: ({ projection }) => commits.push(projection),
      initial: bootstrappedProjection(),
      isCurrent: () => true,
      rpc: new FabricWorkRpc(asGatewayRequest(request)),
      scope,
      sessionId: "runtime-1",
    });

    expect(commits[0]).toMatchObject({
      cursor: null,
      ledger_id: null,
      reset_ledger_hint: replacedLedgerFixture.data.ledger_id,
    });
    expect(result.projection.ledger_id).toBe(
      replacedLedgerFixture.data.ledger_id,
    );
  });
});

describe("PWA durable Attention receipts", () => {
  it("retains the pending card when a stale/mismatched receipt is returned", async () => {
    const base = bootstrappedProjection();
    const attentionFixture = structuredClone(sensitiveAttentionFixture);
    attentionFixture.watermark = 101;
    attentionFixture.cursor = 101;
    attentionFixture.events[0]!.event_id = 101;
    const attentionPage = parsedPage(attentionFixture);
    const projection = applyWorkSyncPage(base, attentionPage, {
      ...scope,
      after: base.cursor as number,
    });
    const attention =
      projection.attention.attn_ffffffffffffffffffffffffffffffff;
    if (!attention) throw new Error("sensitive attention fixture is missing");
    const rpc = new FabricWorkRpc(
      asGatewayRequest(
        vi.fn(async () => ({
          attention_id: "attn_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
          attention_version: attention.version + 1,
          delivered: true,
          mutation_id: "mutation-attention",
          replayed: false,
          state: "resolved",
        })),
      ),
    );

    await expect(
      rpc.respondToAttention("runtime-1", attention, {
        action: "submit",
        idempotency_key: "33333333-3333-4333-8333-333333333333",
        value: "not persisted",
      }),
    ).rejects.toBeInstanceOf(WorkContractInvalidError);
    expect(projection.attention[attention.attention_id]).toBe(attention);
    expect(projection.attention[attention.attention_id]?.state).toBe("pending");
  });
});
