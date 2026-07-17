import { desktopBrand } from '@/brand'
import { relativeTime } from '@/lib/time'
import type { PetOverlaySession } from '@/store/pet-overlay-sessions'

interface PetOverlaySessionPanelProps {
  onDock: () => void
  onOpenApp: () => void
  onOpenSession: (sessionId: string) => void
  sessions: PetOverlaySession[]
}

const STATUS = {
  active: { color: 'var(--ui-accent)', label: 'Open' },
  attention: { color: '#f59e0b', label: 'Needs input' },
  idle: { color: 'var(--ui-text-quaternary)', label: '' },
  working: { color: 'var(--ui-accent)', label: 'Running' }
} as const

function sessionMeta(session: PetOverlaySession): string {
  const state = STATUS[session.status].label || relativeTime(session.lastActive * 1000)
  const profile = session.profile && session.profile !== 'default' ? session.profile : null
  const model = session.model?.split('/').at(-1)

  return [state, profile, model].filter(Boolean).join(' · ')
}

export function PetOverlaySessionPanel({
  onDock,
  onOpenApp,
  onOpenSession,
  sessions
}: PetOverlaySessionPanelProps) {
  const live = sessions.filter(session => session.status === 'attention' || session.status === 'working').length

  return (
    <section
      aria-label="Fabric sessions"
      onContextMenu={event => event.preventDefault()}
      onPointerDown={event => event.stopPropagation()}
      onPointerUp={event => event.stopPropagation()}
      style={{
        background: 'color-mix(in srgb, var(--ui-bg-elevated) 94%, transparent)',
        border: '1px solid var(--ui-stroke-secondary)',
        borderRadius: 8,
        boxShadow: '0 12px 36px rgba(0,0,0,0.34)',
        color: 'var(--foreground)',
        marginBottom: 8,
        overflow: 'hidden',
        width: 260
      }}
    >
      <header
        style={{
          alignItems: 'center',
          borderBottom: '1px solid var(--ui-stroke-secondary)',
          display: 'flex',
          justifyContent: 'space-between',
          padding: '8px 10px'
        }}
      >
        <strong style={{ fontSize: 12, fontWeight: 600 }}>{desktopBrand.productName} sessions</strong>
        <span style={{ color: live ? 'var(--ui-accent)' : 'var(--ui-text-tertiary)', fontSize: 10 }}>
          {live ? `${live} live` : 'Recent'}
        </span>
      </header>

      <div style={{ display: 'grid', gap: 2, maxHeight: 228, overflowY: 'auto', padding: 4 }}>
        {sessions.length ? (
          sessions.map(session => {
            const status = STATUS[session.status]

            return (
              <button
                aria-label={`Open session ${session.title}`}
                key={session.id}
                onClick={() => onOpenSession(session.id)}
                style={{
                  alignItems: 'center',
                  background: session.status === 'active' ? 'var(--ui-control-active-background)' : 'transparent',
                  border: 0,
                  borderRadius: 5,
                  color: 'inherit',
                  cursor: 'pointer',
                  display: 'grid',
                  gap: '1px 8px',
                  gridTemplateColumns: '8px minmax(0, 1fr)',
                  padding: '7px 8px',
                  textAlign: 'left',
                  width: '100%'
                }}
                type="button"
              >
                <span
                  aria-hidden="true"
                  style={{
                    background: status.color,
                    borderRadius: 999,
                    boxShadow: session.status === 'working' ? `0 0 0 3px color-mix(in srgb, ${status.color} 18%, transparent)` : undefined,
                    gridRow: '1 / span 2',
                    height: 6,
                    width: 6
                  }}
                />
                <span style={{ fontSize: 11, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {session.title}
                </span>
                <span style={{ color: 'var(--ui-text-tertiary)', fontSize: 9, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {sessionMeta(session)}
                </span>
              </button>
            )
          })
        ) : (
          <div style={{ color: 'var(--ui-text-tertiary)', fontSize: 10, padding: '16px 8px', textAlign: 'center' }}>
            No recent sessions
          </div>
        )}
      </div>

      <footer
        style={{
          borderTop: '1px solid var(--ui-stroke-secondary)',
          display: 'grid',
          gap: 4,
          gridTemplateColumns: '1fr 1fr',
          padding: 4
        }}
      >
        <PanelAction label={`Open ${desktopBrand.productName}`} onClick={onOpenApp} />
        <PanelAction label="Dock pet" onClick={onDock} />
      </footer>
    </section>
  )
}

function PanelAction({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: 'transparent',
        border: 0,
        borderRadius: 4,
        color: 'var(--ui-text-secondary)',
        cursor: 'pointer',
        fontSize: 9,
        padding: '6px 4px'
      }}
      type="button"
    >
      {label}
    </button>
  )
}
