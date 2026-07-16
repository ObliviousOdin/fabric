// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { exposePluginSDK } from "./registry";
import { PluginSlot, unregisterPluginSlots } from "./slots";
import workPluginBundle from "../../../plugins/kanban/dashboard/dist/index.js?raw";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function buttonWithText(container: ParentNode, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === text,
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`button not found: ${text}`);
  }
  return button;
}

function clearLocalStorageIfAvailable(): void {
  try {
    window.localStorage?.clear();
  } catch {
    // Restricted/private browser contexts may deny storage entirely.
  }
}

function installMemoryLocalStorage(): Storage {
  const values = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return values.size;
    },
    clear() {
      values.clear();
    },
    getItem(key) {
      return values.get(String(key)) ?? null;
    },
    key(index) {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key) {
      values.delete(String(key));
    },
    setItem(key, value) {
      values.set(String(key), String(value));
    },
  };
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: storage,
  });
  return storage;
}

describe("Kanban Work chat rail", () => {
  let container: HTMLDivElement;
  let root: Root;
  let localStorageDescriptor: PropertyDescriptor | undefined;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    localStorageDescriptor = Object.getOwnPropertyDescriptor(
      window,
      "localStorage",
    );
    clearLocalStorageIfAvailable();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      unregisterPluginSlots("kanban");
      root.unmount();
    });
    container.remove();
    if (localStorageDescriptor) {
      Object.defineProperty(window, "localStorage", localStorageDescriptor);
    } else {
      Reflect.deleteProperty(window, "localStorage");
    }
    clearLocalStorageIfAvailable();
    vi.restoreAllMocks();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("retains the committed board result when the board changes in flight", async () => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("Storage denied", "SecurityError");
      },
    });
    const tracked = deferred<{ task: { id: string; status: string } }>();
    const boards = {
      current: "default",
      boards: [
        { slug: "default", name: "Default", counts: {} },
        { slug: "other", name: "Other", counts: {} },
      ],
    };
    const fetchJSON = vi.fn(
      (url: string, init?: { method?: string }) => {
        if (url === "/api/plugins/kanban/boards") return Promise.resolve(boards);
        if (
          url === "/api/plugins/kanban/tasks?board=default" &&
          init?.method === "POST"
        ) {
          return tracked.promise;
        }
        return Promise.reject(new Error(`unexpected request: ${url}`));
      },
    );

    exposePluginSDK();
    const sdk = window.__FABRIC_PLUGIN_SDK__ as unknown as {
      fetchJSON: typeof fetchJSON;
      useI18n: () => { t: { kanban: null }; locale: string };
    };
    sdk.fetchJSON = fetchJSON;
    sdk.useI18n = () => ({ t: { kanban: null }, locale: "en" });
    window.eval(workPluginBundle);

    await act(async () => {
      root.render(
        <PluginSlot
          name="chat:rail"
          slotProps={{
            active: true,
            currentChat: {
              id: "session-42",
              status: "ready",
              title: "Release planning",
            },
          }}
        />,
      );
      await Promise.resolve();
    });

    const trackButton = buttonWithText(container, "Track chat in Work");
    await act(async () => trackButton.click());

    const boardSelect = container.querySelector('[role="combobox"]');
    if (!(boardSelect instanceof HTMLButtonElement)) {
      throw new Error("Work board selector did not render");
    }
    await act(async () => boardSelect.click());
    const otherOption = Array.from(
      container.querySelectorAll('[role="option"]'),
    ).find((option) => option.textContent?.trim() === "Other");
    if (!(otherOption instanceof HTMLElement)) {
      throw new Error("Other board option did not render");
    }
    await act(async () => otherOption.click());
    await act(async () => {
      tracked.resolve({ task: { id: "t_chat", status: "triage" } });
      await tracked.promise;
      await Promise.resolve();
    });

    expect(boardSelect.textContent).toContain("Other");
    expect(container.textContent).toContain("Tracked as t_chat on Default.");
    const committedButton = buttonWithText(container, "Tracked in Work");
    expect(committedButton.disabled).toBe(true);

    await act(async () => committedButton.click());
    const taskPosts = fetchJSON.mock.calls.filter(
      ([url, init]) =>
        String(url).includes("/tasks?") && init?.method === "POST",
    );
    expect(taskPosts).toHaveLength(1);
  });

  it("adopts a board selected on Work when the hidden Chat rail becomes active", async () => {
    const storage = installMemoryLocalStorage();
    const boards = {
      current: "default",
      boards: [
        { slug: "default", name: "Default", counts: {} },
        { slug: "other", name: "Other", counts: {} },
      ],
    };
    const fetchJSON = vi.fn(() => Promise.resolve(boards));
    const currentChat = {
      id: "session-42",
      status: "ready",
      title: "Release planning",
    };

    exposePluginSDK();
    const sdk = window.__FABRIC_PLUGIN_SDK__ as unknown as {
      fetchJSON: typeof fetchJSON;
      useI18n: () => { t: { kanban: null }; locale: string };
    };
    sdk.fetchJSON = fetchJSON;
    sdk.useI18n = () => ({ t: { kanban: null }, locale: "en" });
    window.eval(workPluginBundle);

    await act(async () => {
      root.render(
        <PluginSlot
          name="chat:rail"
          slotProps={{ active: true, currentChat }}
        />,
      );
      await Promise.resolve();
    });
    expect(buttonWithText(container, "Default")).toBeTruthy();

    await act(async () => {
      root.render(
        <PluginSlot
          name="chat:rail"
          slotProps={{ active: false, currentChat }}
        />,
      );
    });
    storage.setItem("fabric.kanban.selectedBoard", "other");
    await act(async () => {
      root.render(
        <PluginSlot
          name="chat:rail"
          slotProps={{ active: true, currentChat }}
        />,
      );
      await Promise.resolve();
    });

    expect(buttonWithText(container, "Other")).toBeTruthy();
    expect(fetchJSON).toHaveBeenCalledTimes(2);
  });

  it("uses the server current board on first load when storage has no selection", async () => {
    installMemoryLocalStorage();
    const fetchJSON = vi.fn(() =>
      Promise.resolve({
        current: "other",
        boards: [
          { slug: "default", name: "Default", counts: {} },
          { slug: "other", name: "Other", counts: {} },
        ],
      }),
    );

    exposePluginSDK();
    const sdk = window.__FABRIC_PLUGIN_SDK__ as unknown as {
      fetchJSON: typeof fetchJSON;
      useI18n: () => { t: { kanban: null }; locale: string };
    };
    sdk.fetchJSON = fetchJSON;
    sdk.useI18n = () => ({ t: { kanban: null }, locale: "en" });
    window.eval(workPluginBundle);

    await act(async () => {
      root.render(
        <PluginSlot
          name="chat:rail"
          slotProps={{
            active: true,
            currentChat: {
              id: "session-42",
              status: "ready",
              title: "Release planning",
            },
          }}
        />,
      );
      await Promise.resolve();
    });

    expect(buttonWithText(container, "Other")).toBeTruthy();
  });
});
