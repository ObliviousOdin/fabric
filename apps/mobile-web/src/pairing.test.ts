import { describe, expect, it } from "vitest";

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
      pairingUri: pairing,
    });
  });

  it("rejects missing or contradictory authentication payloads", () => {
    const invalid = [
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=token",
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=gated&token=unexpected",
      "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=other",
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
        `#pair=${encodeURIComponent("fabric://pair?v=1&url=https%3A%2F%2Fuser%3Apass%40agent.example.test")}`,
      ),
    ).toBeNull();
  });

  it("returns null when there is no pairing fragment", () => {
    expect(parsePairingHash("")).toBeNull();
    expect(parsePairingHash("#other=value")).toBeNull();
  });
});
