/**
 * A persistent Chat may stay hidden only after it has mounted once while
 * active. Plugin/lazy resolution that finishes after a quick route-away must
 * not create a brand-new hidden PTY with the wrong route identity.
 */
export function shouldRenderPersistentChat(
  isChatRoute: boolean,
  hasMountedActiveChat: boolean,
  pluginsLoading: boolean,
): boolean {
  return !pluginsLoading && (isChatRoute || hasMountedActiveChat);
}

/** Retain Chat only after the lazy page reports a real active commit. */
export function usePersistentActiveMount() {
  const [hasMountedActiveChat, setHasMountedActiveChat] = useState(false);
  const markActiveChatMounted = useCallback(
    () => setHasMountedActiveChat(true),
    [],
  );
  return { hasMountedActiveChat, markActiveChatMounted };
}
import { useCallback, useState } from "react";
