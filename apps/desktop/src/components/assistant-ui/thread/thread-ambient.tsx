'use client'

import { useAuiState } from '@assistant-ui/react'
import type { FC } from 'react'

import { cn } from '@/lib/utils'

// A subtle ambient glow behind the thread that intensifies while the agent is
// working — the desktop counterpart to the concept's reactive backdrop. Purely
// decorative: aria-hidden, pointer-events-none, painted behind the message list
// (-z-10) so it can never obscure or intercept content, low opacity, and inert
// under reduced motion.

export const ThreadAmbientView: FC<{ active: boolean }> = ({ active }) => (
  <div
    aria-hidden
    className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
    data-active={active ? 'true' : 'false'}
    data-slot="aui_thread-ambient"
  >
    <div
      className={cn(
        'absolute -left-1/4 -top-1/4 h-2/3 w-2/3 rounded-full blur-3xl transition-opacity duration-1000',
        'bg-[radial-gradient(circle,rgba(139,92,246,0.16),transparent_70%)]',
        active ? 'animate-pulse opacity-100 motion-reduce:animate-none' : 'opacity-40'
      )}
    />
    <div
      className={cn(
        'absolute -bottom-1/4 -right-1/4 h-2/3 w-2/3 rounded-full blur-3xl transition-opacity duration-1000',
        'bg-[radial-gradient(circle,rgba(217,70,239,0.13),transparent_70%)]',
        active ? 'animate-pulse opacity-90 motion-reduce:animate-none' : 'opacity-30'
      )}
      style={{ animationDelay: '700ms' }}
    />
  </div>
)

export const ThreadAmbient: FC = () => {
  const active = useAuiState(s => s.thread.isRunning)

  return <ThreadAmbientView active={Boolean(active)} />
}
