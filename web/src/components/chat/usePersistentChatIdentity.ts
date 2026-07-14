import { useState } from "react";

export interface PersistentChatIdentity {
  channel: string;
  profile: string;
  resumeParam: string | null;
}

function generateChannelId(scope?: string): string {
  const prefix = scope ? "chat" : "chat-fresh";
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Math.random().toString(36).slice(2)}-${Date.now().toString(
    36,
  )}`;
}

/**
 * Own the durable identity of the persistently mounted dashboard Chat.
 *
 * Router search parameters belong to the active route. Once Chat is hidden,
 * navigation may replace them with Home/Admin query state; that must never
 * tear down a live PTY. We therefore adopt resume/profile changes only while
 * Chat owns the active route, and apply a pending scope change when the user
 * returns.
 */
export function usePersistentChatIdentity(
  isActive: boolean,
  routeResumeParam: string | null,
  routeProfile: string,
): PersistentChatIdentity {
  const createIdentity = (): PersistentChatIdentity => ({
    channel: generateChannelId(`${routeResumeParam ?? ""}\0${routeProfile}`),
    profile: routeProfile,
    resumeParam: routeResumeParam,
  });
  const [identity, setIdentity] = useState<PersistentChatIdentity>(createIdentity);

  if (
    isActive &&
    (identity.resumeParam !== routeResumeParam || identity.profile !== routeProfile)
  ) {
    const next = {
      channel: generateChannelId(
        `${routeResumeParam ?? ""}\0${routeProfile}`,
      ),
      profile: routeProfile,
      resumeParam: routeResumeParam,
    };
    setIdentity(next);
    return next;
  }

  return identity;
}
