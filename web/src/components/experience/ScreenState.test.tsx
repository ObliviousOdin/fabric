import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ScreenState } from "./ScreenState";
import { SCREEN_STATE_KINDS, SCREEN_STATE_PRESENTATION } from "./screen-state";

describe("ScreenState", () => {
  it("defines a presentation for every non-normal enterprise state", () => {
    const nonNormal = SCREEN_STATE_KINDS.filter((kind) => kind !== "normal");
    expect(Object.keys(SCREEN_STATE_PRESENTATION).sort()).toEqual(
      [...nonNormal].sort(),
    );
  });

  it("uses alert semantics for a permission denial", () => {
    const html = renderToStaticMarkup(
      <ScreenState
        kind="permission-denied"
        title="Access required"
        description="Your current role cannot view this resource."
      />,
    );
    expect(html).toContain('role="alert"');
    expect(html).toContain("Access required");
  });

  it("announces loading without implying an error", () => {
    const html = renderToStaticMarkup(
      <ScreenState
        kind="loading"
        title="Loading work"
        description="Fetching the latest durable work."
      />,
    );
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-live="polite"');
    expect(html).toContain('aria-busy="true"');
  });
});
