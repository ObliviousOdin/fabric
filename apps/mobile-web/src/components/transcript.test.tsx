import type { RemoteMessage } from "@fabric/shared";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { Transcript } from "./transcript";

const emptyMessages: RemoteMessage[] = [];

describe("Transcript empty state", () => {
  it("offers suggestions only when the gateway is connected", () => {
    const html = renderToStaticMarkup(
      <Transcript
        connected
        messages={emptyMessages}
        onSuggestion={vi.fn()}
        running={false}
      />,
    );

    expect(html).toContain("Ready on your gateway");
    expect(html).toContain("What are we working on?");
    expect(html).toContain("Review the current branch");
  });

  it("does not present an unavailable gateway as ready", () => {
    const html = renderToStaticMarkup(
      <Transcript
        connected={false}
        messages={emptyMessages}
        onSuggestion={vi.fn()}
        running={false}
      />,
    );

    expect(html).toContain("Gateway disconnected");
    expect(html).toContain("Reconnect to continue.");
    expect(html).toContain("Your draft is safe.");
    expect(html).not.toContain("Ready on your gateway");
    expect(html).not.toContain("Review the current branch");
  });
});
