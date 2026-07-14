// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "./context";
import { useI18n } from "./use-i18n";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function LocaleProbe() {
  const { locale, setLocale, t } = useI18n();
  return (
    <>
      <output data-locale>{`${locale}:${t.common.cancel}`}</output>
      <button type="button" onClick={() => setLocale("de")}>
        Deutsch
      </button>
    </>
  );
}

describe("I18nProvider deferred locales", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    document.documentElement.lang = "en";
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("loads a selected dictionary asynchronously and persists the locale", async () => {
    await act(async () =>
      root.render(
        <I18nProvider>
          <LocaleProbe />
        </I18nProvider>,
      ),
    );
    expect(container.querySelector("[data-locale]")?.textContent).toBe(
      "en:Cancel",
    );

    await act(async () => {
      container.querySelector("button")?.click();
    });

    for (let attempt = 0; attempt < 10; attempt += 1) {
      if (
        container.querySelector("[data-locale]")?.textContent === "de:Abbrechen"
      ) {
        break;
      }
      await act(async () => {
        await new Promise((resolve) => window.setTimeout(resolve, 10));
      });
    }

    expect(container.querySelector("[data-locale]")?.textContent).toBe(
      "de:Abbrechen",
    );
    expect(localStorage.getItem("fabric-locale")).toBe("de");
    expect(document.documentElement.lang).toBe("de");
  });
});
