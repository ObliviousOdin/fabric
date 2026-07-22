import { describe, expect, it } from "vitest";

import {
  buildSocialPrompt,
  SOCIAL_POST_FENCE,
  type SocialRequest,
} from "./social-prompt";

const base: SocialRequest = {
  brief: "Shipping our new agent dashboard after six weeks of work",
  channel: "linkedin",
  format: "hook-story",
  goal: "authority",
  includeImage: true,
  tone: "candid",
};

describe("buildSocialPrompt", () => {
  it("includes the brief, the channel, and the copy-paste fence tag", () => {
    const prompt = buildSocialPrompt(base);
    expect(prompt).toContain(base.brief);
    expect(prompt).toContain("LinkedIn");
    expect(prompt).toContain(`\`${SOCIAL_POST_FENCE}\``);
  });

  it("asks for an image when includeImage is true and skips it otherwise", () => {
    expect(buildSocialPrompt({ ...base, includeImage: true })).toContain(
      "Artifacts",
    );
    const noImage = buildSocialPrompt({ ...base, includeImage: false });
    expect(noImage.toLowerCase()).toContain("text only");
    expect(noImage).not.toContain("Artifacts");
  });

  it("varies the instructions with the chosen tone, goal, and format", () => {
    const candid = buildSocialPrompt({ ...base, tone: "candid" });
    const analytical = buildSocialPrompt({ ...base, tone: "analytical" });
    expect(candid).not.toBe(analytical);

    const authority = buildSocialPrompt({ ...base, goal: "authority" });
    const engagement = buildSocialPrompt({ ...base, goal: "engagement" });
    expect(authority).not.toBe(engagement);

    const story = buildSocialPrompt({ ...base, format: "hook-story" });
    const tips = buildSocialPrompt({ ...base, format: "tips" });
    expect(story).not.toBe(tips);
  });

  it("normalizes whitespace and control characters in the brief", () => {
    const prompt = buildSocialPrompt({
      ...base,
      brief: "line one\n\tline two   spaced",
    });
    expect(prompt).toContain("line one line two spaced");
    expect(prompt).not.toContain("\t");
  });

  it("is deterministic for the same request", () => {
    expect(buildSocialPrompt(base)).toBe(buildSocialPrompt(base));
  });
});
