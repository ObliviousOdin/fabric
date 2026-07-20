import { describe, expect, it } from "vitest";

import pairingV2Fixture from "../../mobile/contracts/fabric-pairing-v2.json";

import { parsePairingHash, parsePairingPayloadHash } from "./pairing";

describe("parsePairingHash", () => {
  it("accepts a valid Fabric pairing URI", () => {
    const pairing =
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=gated";

    expect(parsePairingHash(`#pair=${encodeURIComponent(pairing)}`)).toBe(pairing);
  });

  it("turns a token fragment into the actual in-memory connection", () => {
    const pairing =
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=token&token=private-session-token";

    expect(parsePairingPayloadHash(`#pair=${encodeURIComponent(pairing)}`)).toEqual({
      connection: {
        authMode: "token",
        baseUrl: "https://agent.example.test/",
        token: "private-session-token",
      },
      kind: "legacy",
      pairingUri: pairing,
    });
  });

  it("recognizes a strict v2 enrollment handoff without creating a connection", () => {
    const enrollment = "A".repeat(43);
    const pairing =
      `fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=${enrollment}&auth=browser`;

    expect(parsePairingPayloadHash(`#pair=${encodeURIComponent(pairing)}`)).toEqual({
      auth: "browser",
      baseUrl: "https://agent.example.test/",
      enrollment,
      kind: "enrollment",
      pairingUri: pairing,
    });
  });

  it("agrees with the canonical v2 pairing corpus", () => {
    for (const fixture of pairingV2Fixture.cases) {
      const parsed = parsePairingPayloadHash(
        `#pair=${encodeURIComponent(fixture.payload)}`,
      );
      if (fixture.valid) {
        expect(parsed, fixture.id).toMatchObject({ kind: "enrollment" });
      } else {
        expect(parsed, fixture.id).toBeNull();
      }
    }
  });

  it("rejects missing or contradictory authentication payloads", () => {
    const invalid = [
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=token",
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=gated&token=unexpected",
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=other",
      `fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=${"A".repeat(42)}&auth=browser`,
      `fabric://pair?v=2&url=http%3A%2F%2Fagent.example.test&enrollment=${"A".repeat(43)}&auth=browser`,
      `fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=${"A".repeat(43)}&auth=browser&token=unexpected`,
      `fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=${"A".repeat(43)}&auth=gated`,
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&url=https%3A%2F%2Fevil.example.test&auth=gated",
      `fabric://pair/?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=${"A".repeat(43)}&auth=browser`,
      `fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test%2F%2F%2F&enrollment=${"A".repeat(43)}&auth=browser`,
    ];

    for (const pairing of invalid) {
      expect(parsePairingPayloadHash(`#pair=${encodeURIComponent(pairing)}`)).toBeNull();
    }
  });

  it("rejects non-Fabric and unsafe gateway URLs", () => {
    expect(parsePairingHash("#pair=https%3A%2F%2Fexample.test")).toBeNull();
    expect(
      parsePairingHash(
        `#pair=${encodeURIComponent("fabric://pair?v=1&url=file%3A%2F%2F%2Fetc%2Fpasswd")}`,
      ),
    ).toBeNull();
    expect(
      parsePairingHash(
        `#pair=${encodeURIComponent("fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test")}`,
      ),
    ).toBeNull();
    expect(
      parsePairingHash(
        `#pair=${encodeURIComponent("fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=gated")}&pair=${encodeURIComponent("fabric://pair?v=1&url=https%3A%2F%2Fevil.example.test&auth=gated")}`,
      ),
    ).toBeNull();
    expect(
      parsePairingHash(
        `#pair=${encodeURIComponent("fabric://pair?v=1&url=https%3A%2F%2Fuser%3Apass%40agent.example.test")}`,
      ),
    ).toBeNull();
  });

  it("returns null when there is no pairing fragment", () => {
    expect(parsePairingHash("")).toBeNull();
    expect(parsePairingHash("#other=value")).toBeNull();
  });
});
