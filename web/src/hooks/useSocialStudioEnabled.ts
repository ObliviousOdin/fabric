import { useSyncExternalStore } from "react";

import {
  isSocialStudioEnabled,
  setSocialStudioEnabled,
  subscribeSocialStudio,
} from "@/lib/social-studio";

/**
 * React binding for the Social Studio preference. Returns the current value and
 * a setter, and re-renders every consumer when the preference flips (in this
 * tab or another). The server snapshot is `false` so the surface stays hidden
 * during any non-DOM render.
 */
export function useSocialStudioEnabled(): [boolean, (enabled: boolean) => void] {
  const enabled = useSyncExternalStore(
    subscribeSocialStudio,
    isSocialStudioEnabled,
    () => false,
  );
  return [enabled, setSocialStudioEnabled];
}
