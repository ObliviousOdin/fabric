// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { FabricBrand } from "./FabricBrand";
import {
  FABRIC_BRAND_ASSETS,
  resolveFabricBrandAsset,
} from "./brand-assets";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("FabricBrand", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  async function render(appearance: "dark" | "light", compact = false) {
    await act(async () => {
      root.render(<FabricBrand appearance={appearance} compact={compact} />);
    });
  }

  it("uses the light-surface wordmark with stable dimensions and one accessible label", async () => {
    await render("light");

    const brand = container.querySelector<HTMLElement>("[data-fabric-brand]");
    const image = brand?.querySelector("img");

    expect(brand?.textContent).toBe("Fabric");
    expect(brand?.dataset.compact).toBe("false");
    expect(image?.getAttribute("src")).toBe(FABRIC_BRAND_ASSETS.wordmark);
    expect(image?.getAttribute("alt")).toBe("");
    expect(image?.getAttribute("aria-hidden")).toBe("true");
    expect(image?.getAttribute("width")).toBe("93");
    expect(image?.getAttribute("height")).toBe("32");
  });

  it("keeps brand assets inside a reverse-proxy base path", () => {
    expect(resolveFabricBrandAsset(FABRIC_BRAND_ASSETS.mark, "/fabric")).toBe(
      "/fabric/brand/fabric-mark.svg",
    );
  });

  it("uses the explicit on-dark wordmark instead of visual blending", async () => {
    await render("dark");

    const image = container.querySelector("[data-fabric-brand] img");
    expect(image?.getAttribute("src")).toBe(FABRIC_BRAND_ASSETS.wordmarkOnDark);
    expect(image?.getAttribute("style")).toBeNull();
  });

  it("uses the compact lowercase-f mark at icon scale", async () => {
    await render("dark", true);

    const brand = container.querySelector<HTMLElement>("[data-fabric-brand]");
    const image = brand?.querySelector("img");

    expect(brand?.dataset.compact).toBe("true");
    expect(image?.getAttribute("src")).toBe(FABRIC_BRAND_ASSETS.mark);
    expect(image?.getAttribute("width")).toBe("18");
    expect(image?.getAttribute("height")).toBe("18");
  });

  it("falls back to stable visible text and retries when the selected asset changes", async () => {
    await render("light");

    const image = container.querySelector<HTMLImageElement>(
      "[data-fabric-brand] img",
    );
    await act(async () => {
      image?.dispatchEvent(new Event("error"));
    });

    const brand = container.querySelector<HTMLElement>("[data-fabric-brand]");
    expect(brand?.querySelector("[data-brand-fallback]")?.textContent).toBe(
      "Fabric",
    );
    expect(brand?.className).toContain("h-8");
    expect(brand?.className).toContain("w-[5.8125rem]");

    await render("dark");
    expect(container.querySelector("[data-brand-fallback]")).toBeNull();
    expect(
      container.querySelector("[data-fabric-brand] img")?.getAttribute("src"),
    ).toBe(FABRIC_BRAND_ASSETS.wordmarkOnDark);
  });
});
