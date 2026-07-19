import { describe, expect, it } from "vitest";

import { publicCliCommand, publicConsolePrompt } from "./public-identity";

describe("public Fabric identity", () => {
  it("renders Fabric CLI commands supplied by the backend", () => {
    expect(publicCliCommand("fabric update")).toBe("fabric update");
    expect(publicCliCommand("fabric -p worker_alpha gateway start")).toBe(
      "fabric -p worker_alpha gateway start",
    );
    expect(publicCliCommand(undefined)).toBe("fabric update");
  });

  it("renders Fabric console prompts supplied by the backend", () => {
    expect(publicConsolePrompt("fabric> ")).toBe("fabric> ");
    expect(publicConsolePrompt()).toBe("fabric> ");
  });
});
