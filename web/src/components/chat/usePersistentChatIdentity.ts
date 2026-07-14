import { useState } from "react";

export const FRESH_CHAT_QUERY_PARAM = "fresh";

export interface PersistentChatIdentity {
  channel: string;
  profile: string;
  resumeParam: string | null;
}

export interface ChatRouteLocation {
  pathname: string;
  search: string;
  hash: string;
}

interface PersistentChatState extends PersistentChatIdentity {
  freshRequestId: string | null;
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

export function createFreshChatRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function freshChatPath(
  requestId = createFreshChatRequestId(),
): string {
  const params = new URLSearchParams({
    [FRESH_CHAT_QUERY_PARAM]: requestId,
  });
  return `/workspace/chat?${params.toString()}`;
}

export function chatLocationWithSearch(
  location: ChatRouteLocation,
  params: URLSearchParams,
): ChatRouteLocation {
  const search = params.toString();
  return {
    pathname: location.pathname,
    search: search ? `?${search}` : "",
    hash: location.hash,
  };
}

/**
 * Keep the visible route aligned with the durable PTY identity.
 *
 * Fresh-session intent is a one-shot directive, while a bare Chat route
 * adopts the already-mounted session. Only Fabric-owned route parameters are
 * changed; other query state and the current hash survive the replacement.
 */
export function reconcilePersistentChatLocation(
  location: ChatRouteLocation,
  durableResumeParam: string | null,
): ChatRouteLocation | null {
  const params = new URLSearchParams(location.search);
  const freshRequestId = params.get(FRESH_CHAT_QUERY_PARAM);
  const routeResumeParam = params.get("resume");

  if (freshRequestId) {
    params.delete(FRESH_CHAT_QUERY_PARAM);
    params.delete("resume");
    return chatLocationWithSearch(location, params);
  }

  if (!routeResumeParam && durableResumeParam) {
    params.set("resume", durableResumeParam);
    return chatLocationWithSearch(location, params);
  }

  return null;
}

/**
 * Own the durable identity of the persistently mounted dashboard Chat.
 *
 * Router search parameters belong to the active route. Once Chat is hidden,
 * navigation may replace them with Home/Admin query state; that must never
 * tear down a live PTY. A missing `resume` on ordinary Chat navigation means
 * "return to the mounted Chat," not "start over"; callers request the latter
 * with a unique `fresh` route directive. Explicit resume/profile changes are
 * still adopted once Chat owns the active route again.
 */
export function usePersistentChatIdentity(
  isActive: boolean,
  routeResumeParam: string | null,
  routeProfile: string,
  freshRequestId: string | null = null,
): PersistentChatIdentity {
  const [identity, setIdentity] = useState<PersistentChatState>(() => {
    const resumeParam = freshRequestId ? null : routeResumeParam;
    return {
      channel: generateChannelId(`${resumeParam ?? ""}\0${routeProfile}`),
      freshRequestId,
      profile: routeProfile,
      resumeParam,
    };
  });

  const freshRequested =
    freshRequestId !== null && freshRequestId !== identity.freshRequestId;
  const profileChanged = identity.profile !== routeProfile;
  const explicitResumeChanged =
    routeResumeParam !== null && identity.resumeParam !== routeResumeParam;

  if (
    isActive &&
    (freshRequested || profileChanged || explicitResumeChanged)
  ) {
    const resumeParam = freshRequested
      ? null
      : routeResumeParam ?? (profileChanged ? null : identity.resumeParam);
    const next = {
      channel: generateChannelId(`${resumeParam ?? ""}\0${routeProfile}`),
      freshRequestId: freshRequestId ?? identity.freshRequestId,
      profile: routeProfile,
      resumeParam,
    };
    setIdentity(next);
    return next;
  }

  return identity;
}
