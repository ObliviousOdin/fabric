import { readFileSync } from "node:fs";

import { extractSocialArtifacts, type SocialSourceMessage } from "@fabric/shared";
import { describe, expect, it } from "vitest";

/**
 * The Social Studio extraction contract is shared across every front-end. The
 * fixture lives with the mobile wire contracts (apps/mobile/contracts) so the
 * Kotlin and Swift ports can be written against the same cases. This test proves
 * the TypeScript implementation matches the fixture, making it the authoritative
 * spec the native ports mirror.
 */
interface ContractCase {
  name: string;
  messages: SocialSourceMessage[];
  expected: unknown[];
}

interface Contract {
  version: number;
  cases: ContractCase[];
}

const contract = JSON.parse(
  readFileSync(
    new URL(
      "../../../apps/mobile/contracts/social-extraction-v1.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Contract;

describe(`social extraction contract v${contract.version}`, () => {
  it("has cases", () => {
    expect(contract.cases.length).toBeGreaterThan(0);
  });

  for (const testCase of contract.cases) {
    it(testCase.name, () => {
      expect(extractSocialArtifacts(testCase.messages)).toEqual(
        testCase.expected,
      );
    });
  }
});
