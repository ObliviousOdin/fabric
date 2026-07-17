import { describe, expect, it } from "vitest";

import { publicCliCommand, publicConsolePrompt } from "./public-identity";

describe("public Fabric identity", () => {
  it("normalizes legacy CLI commands supplied by older backends", () => {
    expect(publicCliCommand("fabric update")).toBe("fabric update");
    expect(publicCliCommand("fabric -p worker_alpha gateway start")).toBe(
      "fabric -p worker_alpha gateway start",
    );
    expect(publicCliCommand("fabric update")).toBe("fabric update");
    expect(publicCliCommand(undefined)).toBe("fabric update");
  });

  it("normalizes legacy console prompts supplied by older backends", () => {
    expect(publicConsolePrompt("fabric> ")).toBe("fabric> ");
    expect(publicConsolePrompt("fabric> ")).toBe("fabric> ");
    expect(publicConsolePrompt()).toBe("fabric> ");
  });
});
