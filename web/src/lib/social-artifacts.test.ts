import { describe, expect, it } from "vitest";

import type { SessionMessage } from "@/lib/api";
import {
  extractSocialArtifacts,
  hasSocialArtifacts,
  isRemoteImage,
} from "./social-artifacts";

function assistant(content: string, timestamp?: number): SessionMessage {
  return { role: "assistant", content, timestamp };
}

function user(content: string): SessionMessage {
  return { role: "user", content };
}

describe("extractSocialArtifacts", () => {
  it("captures the caption from a linkedin-post fenced block", () => {
    const messages = [
      user("Draft me a post about launching Fabric"),
      assistant(
        "Here is your post:\n\n```linkedin-post\nWe just shipped Fabric.\n\nHere is why it matters.\n```\n\nWant tweaks?",
        1_700_000_000,
      ),
    ];

    const artifacts = extractSocialArtifacts(messages);
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
    const messages = [
      assistant(
        "```linkedin-post\nBig news today.\n```\n\n## Artifacts\n\n![Launch graphic](assets/launch.png)",
      ),
    ];
    const [artifact] = extractSocialArtifacts(messages);
    expect(artifact.caption).toBe("Big news today.");
    expect(artifact.imagePath).toBe("assets/launch.png");
  });

  it("falls back to a bare image path under an Artifacts heading", () => {
    const messages = [
      assistant(
        "```linkedin-post\nA lesson learned.\n```\n\nArtifacts:\n- ./out/post-image.jpg",
      ),
    ];
    const [artifact] = extractSocialArtifacts(messages);
    expect(artifact.imagePath).toBe("./out/post-image.jpg");
  });

  it("returns a null image when none is present", () => {
    const messages = [assistant("```linkedin-post\nText only post.\n```")];
    const [artifact] = extractSocialArtifacts(messages);
    expect(artifact.imagePath).toBeNull();
  });

  it("ignores fenced blocks with an unrelated language", () => {
    const messages = [
      assistant("```python\nprint('not a post')\n```"),
      assistant("Some prose without any fence."),
    ];
    expect(extractSocialArtifacts(messages)).toHaveLength(0);
  });

  it("captures multiple post blocks across the conversation", () => {
    const messages = [
      assistant("```linkedin-post\nDraft one.\n```"),
      user("try another angle"),
      assistant("```linkedin-post\nDraft two.\n```"),
    ];
    const artifacts = extractSocialArtifacts(messages);
    expect(artifacts.map((a) => a.caption)).toEqual([
      "Draft one.",
      "Draft two.",
    ]);
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
