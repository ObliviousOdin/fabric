// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { LocalOllamaSetupCard } from "./LocalOllamaSetupCard";

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

const buttonNamed = (
  container: HTMLElement,
  name: string,
): HTMLButtonElement => {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === name,
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button not found: ${name}`);
  }
  return button;
};

describe("LocalOllamaSetupCard", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    vi.spyOn(api, "getLocalModelProviders").mockResolvedValue({
      providers: [
        {
          id: "ollama",
          name: "Ollama (Local)",
          description: "Native local Ollama",
          default_base_url: "http://127.0.0.1:11434",
          base_url: "http://127.0.0.1:11434",
          configured: false,
          model: "",
          discovery: "explicit",
          setup_command: "fabric model",
          pull_command: "fabric ollama pull MODEL",
        },
      ],
    });
    vi.spyOn(api, "discoverLocalOllama").mockResolvedValue({
      provider: "ollama",
      base_url: "http://127.0.0.1:11434",
      state: "reachable",
      models: ["qwen3:latest", "llama3.2:latest"],
      issue_code: null,
    });
    vi.spyOn(api, "configureLocalOllama").mockResolvedValue({
      ok: true,
      provider: "ollama",
      model: "qwen3:latest",
      base_url: "http://127.0.0.1:11434",
      local_ai_enabled: true,
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("discovers only on demand and configures the first installed model", async () => {
    const configured = vi.fn();
    await act(async () => {
      root.render(<LocalOllamaSetupCard onConfigured={configured} />);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.discoverLocalOllama).not.toHaveBeenCalled();
    expect(container.textContent).toContain(
      "Discovery runs only when you press Refresh",
    );

    await act(async () => {
      buttonNamed(container, "Refresh").click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.discoverLocalOllama).toHaveBeenCalledWith(
      "http://127.0.0.1:11434",
    );
    expect(container.textContent).toContain("2 installed models found");

    await act(async () => {
      buttonNamed(container, "Use model").click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.configureLocalOllama).toHaveBeenCalledWith(
      "http://127.0.0.1:11434",
      "qwen3:latest",
    );
    expect(configured).toHaveBeenCalledTimes(1);
  });
});
