import { describe, expect, it } from "vitest";

import { resolveWorkspaceImagePath } from "./workspace-image-path";

describe("resolveWorkspaceImagePath", () => {
  it("resolves a relative artifact against the producing session cwd", () => {
    expect(resolveWorkspaceImagePath("./output/post.png", "/workspace/project")).toBe(
      "/workspace/project/output/post.png",
    );
  });

  it("preserves remote and absolute paths", () => {
    expect(resolveWorkspaceImagePath("https://example.test/post.png", "/workspace/project")).toBe(
      "https://example.test/post.png",
    );
    expect(resolveWorkspaceImagePath("/tmp/post.png", "/workspace/project")).toBe("/tmp/post.png");
  });
});
