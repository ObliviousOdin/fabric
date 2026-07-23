import { describe, expect, it } from "vitest";

import {
  buildSocialPrompt,
  extractSocialArtifacts,
  hasSocialArtifacts,
  isRemoteImage,
  SOCIAL_POST_FENCE,
  type SocialRequest,
  type SocialSourceMessage,
} from "./social";

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
    expect(buildSocialPrompt({ ...base, tone: "candid" })).not.toBe(
      buildSocialPrompt({ ...base, tone: "analytical" }),
    );
    expect(buildSocialPrompt({ ...base, goal: "authority" })).not.toBe(
      buildSocialPrompt({ ...base, goal: "engagement" }),
    );
    expect(buildSocialPrompt({ ...base, format: "hook-story" })).not.toBe(
      buildSocialPrompt({ ...base, format: "tips" }),
    );
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

function assistant(content: string, timestamp?: number): SocialSourceMessage {
  return { role: "assistant", content, timestamp };
}

function user(content: string): SocialSourceMessage {
  return { role: "user", content };
}

describe("extractSocialArtifacts", () => {
  it("captures the caption from a linkedin-post fenced block", () => {
    const artifacts = extractSocialArtifacts([
      user("Draft me a post about launching Fabric"),
      assistant(
        "Here is your post:\n\n```linkedin-post\nWe just shipped Fabric.\n\nHere is why it matters.\n```\n\nWant tweaks?",
        1_700_000_000,
      ),
    ]);
    expect(artifacts).toHaveLength(1);
    expect(artifacts[0].caption).toBe(
      "We just shipped Fabric.\n\nHere is why it matters.",
    );
    expect(artifacts[0].messageIndex).toBe(1);
    expect(artifacts[0].timestamp).toBe(1_700_000_000);
  });

  it("never reads a user message even if it names the fence", () => {
    const messages = [
      user("Put the result in a ```linkedin-post``` block please"),
    ];
    expect(extractSocialArtifacts(messages)).toHaveLength(0);
    expect(hasSocialArtifacts(messages)).toBe(false);
  });

  it("pulls a markdown image path from the same message", () => {
    const [artifact] = extractSocialArtifacts([
      assistant(
        "```linkedin-post\nBig news today.\n```\n\n## Artifacts\n\n![Launch graphic](assets/launch.png)",
      ),
    ]);
    expect(artifact.caption).toBe("Big news today.");
    expect(artifact.imagePath).toBe("assets/launch.png");
  });

  it("falls back to a bare image path under an Artifacts heading", () => {
    const [artifact] = extractSocialArtifacts([
      assistant(
        "```linkedin-post\nA lesson learned.\n```\n\nArtifacts:\n- ./out/post-image.jpg",
      ),
    ]);
    expect(artifact.imagePath).toBe("./out/post-image.jpg");
  });

  it("returns a null image when none is present", () => {
    const [artifact] = extractSocialArtifacts([
      assistant("```linkedin-post\nText only post.\n```"),
    ]);
    expect(artifact.imagePath).toBeNull();
  });

  it("ignores fenced blocks with an unrelated language", () => {
    expect(
      extractSocialArtifacts([
        assistant("```python\nprint('not a post')\n```"),
        assistant("Some prose without any fence."),
      ]),
    ).toHaveLength(0);
  });

  it("captures multiple post blocks across the conversation", () => {
    const artifacts = extractSocialArtifacts([
      assistant("```linkedin-post\nDraft one.\n```"),
      user("try another angle"),
      assistant("```linkedin-post\nDraft two.\n```"),
    ]);
    expect(artifacts.map((a) => a.caption)).toEqual(["Draft one.", "Draft two."]);
    expect(new Set(artifacts.map((a) => a.id)).size).toBe(2);
  });
});

describe("isRemoteImage", () => {
  it("distinguishes URLs from workspace paths", () => {
    expect(isRemoteImage("https://example.com/a.png")).toBe(true);
    expect(isRemoteImage("assets/launch.png")).toBe(false);
    expect(isRemoteImage("/home/user/out.png")).toBe(false);
  });
});
