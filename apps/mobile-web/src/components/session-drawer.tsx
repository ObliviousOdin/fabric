import type { RemoteSessionSummary } from "@fabric/shared";
import {
  IconLogout,
  IconMessagePlus,
  IconRefresh,
  IconSearch,
  IconX,
} from "@tabler/icons-react";
import { useMemo, useState } from "react";

interface SessionDrawerProps {
  activeStoredId: null | string;
  onClose: () => void;
  onDisconnect: () => void;
  onNew: () => void;
  onRefresh: () => void;
  onSelect: (id: string) => void;
  open: boolean;
  sessions: RemoteSessionSummary[];
}

function compactDate(timestamp: number): string {
  if (!timestamp) {
    return "";
  }
  const date = new Date(timestamp < 10_000_000_000 ? timestamp * 1000 : timestamp);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { day: "numeric", month: "short" });
}

export function SessionDrawer({
  activeStoredId,
  onClose,
  onDisconnect,
  onNew,
  onRefresh,
  onSelect,
  open,
  sessions,
}: SessionDrawerProps) {
  const [query, setQuery] = useState("");
  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return sessions;
    }
    return sessions.filter((session) =>
      `${session.title} ${session.preview} ${session.source}`
        .toLowerCase()
        .includes(normalized),
    );
  }, [query, sessions]);

  return (
    <>
      <button
        className={`drawer-scrim ${open ? "open" : ""}`}
        type="button"
        aria-label="Close sessions"
        onClick={onClose}
      />
      <aside className={`session-drawer ${open ? "open" : ""}`} aria-label="Fabric sessions">
        <header className="drawer-header">
          <div className="brand-lockup compact">
            <img src={`${import.meta.env.BASE_URL}fabric-mark-192.png`} alt="" />
            <span>Fabric</span>
          </div>
          <button className="icon-button drawer-close" type="button" aria-label="Close" onClick={onClose}>
            <IconX size={20} />
          </button>
        </header>

        <button className="new-session-button" type="button" onClick={onNew}>
          <IconMessagePlus size={18} stroke={1.7} />
          New session
        </button>

        <label className="session-search">
          <IconSearch size={16} stroke={1.7} />
          <span className="sr-only">Search sessions</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search sessions"
          />
        </label>

        <div className="session-list-heading">
          <span>Recent</span>
          <button type="button" aria-label="Refresh sessions" onClick={onRefresh}>
            <IconRefresh size={15} />
          </button>
        </div>

        <nav className="session-list" aria-label="Recent sessions">
          {visible.length ? (
            visible.map((session) => {
              const selected = session.id === activeStoredId;
              return (
                <button
                  className={`session-row ${selected ? "active" : ""}`}
                  key={session.id}
                  type="button"
                  aria-current={selected ? "page" : undefined}
                  onClick={() => onSelect(session.id)}
                >
                  <span className="session-row-topline">
                    <strong>{session.title || "Untitled session"}</strong>
                    <time>{compactDate(session.started_at)}</time>
                  </span>
                  <span className="session-preview">
                    {session.preview || `${session.message_count} messages`}
                  </span>
                </button>
              );
            })
          ) : (
            <p className="empty-session-list">
              {query ? "No sessions match." : "No saved sessions yet."}
            </p>
          )}
        </nav>

        <footer className="drawer-footer">
          <button type="button" onClick={onDisconnect}>
            <IconLogout size={17} />
            Disconnect gateway
          </button>
        </footer>
      </aside>
    </>
  );
}
