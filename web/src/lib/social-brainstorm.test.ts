// @vitest-environment jsdom

import { SOCIAL_POST_FENCE } from "@fabric/shared";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  buildSocialBrainstormPrompt,
  hasBrainstormed,
  markBrainstormed,
  resolveSocialStages,
  SOCIAL_BRAINSTORMED_KEY,
  type SocialBrainstormPlan,
} from "./social-brainstorm";

const basePlan: SocialBrainstormPlan = {
  cadence: "weekdays",
  goal: "authority",
  includeImage: true,
  postCount: 5,
  tone: "candid",
  topic: "Shipping our agent dashboard in six weeks",
};

describe("resolveSocialStages", () => {
  it("locks everything but the brainstorm on a fresh browser", () => {
    const access = resolveSocialStages({
      hasArtifacts: false,
      hasBrainstormed: false,
    });
    expect(access.initialStage).toBe("brainstorm");
    expect(access.composeUnlocked).toBe(false);
    expect(access.libraryUnlocked).toBe(false);
  });

  it("unlocks compose after a brainstorm but keeps the empty library locked", () => {
    const access = resolveSocialStages({
      hasArtifacts: false,
      hasBrainstormed: true,
    });
    expect(access.initialStage).toBe("brainstorm");
    expect(access.composeUnlocked).toBe(true);
    expect(access.libraryUnlocked).toBe(false);
  });

  it("unlocks everything and lands on the library once artifacts exist", () => {
    for (const hasBrainstormed of [false, true]) {
      const access = resolveSocialStages({ hasArtifacts: true, hasBrainstormed });
      expect(access.initialStage).toBe("library");
      expect(access.composeUnlocked).toBe(true);
      expect(access.libraryUnlocked).toBe(true);
    }
  });
});

describe("brainstormed persistence", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it("defaults to false and round-trips through storage", () => {
    expect(hasBrainstormed()).toBe(false);
    markBrainstormed();
    expect(hasBrainstormed()).toBe(true);
    expect(localStorage.getItem(SOCIAL_BRAINSTORMED_KEY)).toBe("true");
  });
});

describe("buildSocialBrainstormPrompt", () => {
  it("is deterministic for the same plan", () => {
    expect(buildSocialBrainstormPrompt(basePlan)).toBe(
      buildSocialBrainstormPrompt(basePlan),
    );
  });

  it("asks for ideas first and keeps the shared post fence for drafts", () => {
    const prompt = buildSocialBrainstormPrompt(basePlan);
    expect(prompt).toContain("sequence of 5 LinkedIn posts");
    expect(prompt).toContain("Propose 5 post ideas");
    expect(prompt).toContain("before you draft anything");
    expect(prompt).toContain(`\`${SOCIAL_POST_FENCE}\``);
  });

  it("constrains drafts to one post (and its image) per reply", () => {
    // The shared artifact parser pairs every fenced block in a message with
    // the first image found in that message, so batched drafts would attach
    // one image to every caption. The handoff must forbid batching.
    const prompt = buildSocialBrainstormPrompt(basePlan);
    expect(prompt).toContain("that one post only");
    expect(prompt).toContain("each draft gets its own reply");
    expect(prompt).toContain("in the same reply as its post");
  });

  it("reflects cadence and the image choice", () => {
    const prompt = buildSocialBrainstormPrompt(basePlan);
    expect(prompt).toContain("one post each weekday");
    expect(prompt).toContain("1200x1200");

    const textOnly = buildSocialBrainstormPrompt({
      ...basePlan,
      cadence: "weekly",
      includeImage: false,
    });
    expect(textOnly).toContain("one post a week");
    expect(textOnly).not.toContain("1200x1200");
    expect(textOnly).toContain("text only");
  });

  it("normalizes control characters and whitespace out of the topic", () => {
    const prompt = buildSocialBrainstormPrompt({
      ...basePlan,
      topic: "line one\nline\ttwo   spaced",
    });
    expect(prompt).toContain("Raw material: line one line two spaced");
  });

  it("bounds a runaway topic to 2000 characters", () => {
    const prompt = buildSocialBrainstormPrompt({
      ...basePlan,
      topic: "x".repeat(5000),
    });
    const line = prompt.split("\n")[0];
    expect(line.length).toBeLessThanOrEqual("Raw material: ".length + 2100);
    expect(line.endsWith("x".repeat(10))).toBe(true);
  });
});
