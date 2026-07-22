// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  isSocialStudioEnabled,
  resetSocialStudioCache,
  setSocialStudioEnabled,
  SOCIAL_STUDIO_ENABLED_KEY,
  subscribeSocialStudio,
} from "./social-studio";

describe("social-studio preference store", () => {
  beforeEach(() => {
    localStorage.clear();
    resetSocialStudioCache();
  });

  afterEach(() => {
    localStorage.clear();
    resetSocialStudioCache();
  });

  it("defaults to disabled when nothing is stored", () => {
    expect(isSocialStudioEnabled()).toBe(false);
  });

  it("reads a persisted 'true' value", () => {
    localStorage.setItem(SOCIAL_STUDIO_ENABLED_KEY, "true");
    resetSocialStudioCache();
    expect(isSocialStudioEnabled()).toBe(true);
  });

  it("persists and reflects the value after setting it", () => {
    setSocialStudioEnabled(true);
    expect(isSocialStudioEnabled()).toBe(true);
    expect(localStorage.getItem(SOCIAL_STUDIO_ENABLED_KEY)).toBe("true");

    setSocialStudioEnabled(false);
    expect(isSocialStudioEnabled()).toBe(false);
    expect(localStorage.getItem(SOCIAL_STUDIO_ENABLED_KEY)).toBe("false");
  });

  it("notifies subscribers on change and stops after unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeSocialStudio(listener);

    setSocialStudioEnabled(true);
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    setSocialStudioEnabled(false);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
