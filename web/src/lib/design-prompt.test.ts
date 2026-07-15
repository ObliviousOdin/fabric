import { describe, expect, it } from "vitest";

import { buildDesignPrompt } from "@fabric/shared";

describe("buildDesignPrompt", () => {
  it("routes a visual reference through the design skill", () => {
    const prompt = buildDesignPrompt({
      artifact: "dashboard",
      brief: "Build an operations console",
      fidelity: "high",
      system: "linear",
    });

    expect(prompt).toContain("/design Build an operations console");
    expect(prompt).toContain("task-oriented dashboard");
    expect(prompt).toContain("Linear reference from popular-web-designs");
    expect(prompt).toContain("Fidelity: High fidelity.");
  });

  it("keeps design-system requests anchored to DESIGN.md", () => {
    const prompt = buildDesignPrompt({
      artifact: "design-system",
      brief: "  Unify the product\u001b with shared tokens  ",
      fidelity: "wireframe",
      system: "project",
    });

    expect(prompt).not.toContain("\u001b");
    expect(prompt).toContain("persistent DESIGN.md design contract");
    expect(prompt).toContain("current project's DESIGN.md");
  });
});
