'use client'

import { FileDiffPanel } from '@/components/chat/diff-lines'

import type { RichFenceProps } from './types'

// Lazy chunk. Renders a ```diff fence as a proper unified-diff panel — added
// and removed lines with a coloured gutter and line numbers — instead of a flat
// syntax-highlighted block, reusing the same FileDiffPanel the tool cards use.
// A diff parses fine on partial input, so (unlike mermaid) it renders while the
// message is still streaming. On any parse issue the registry's RichBoundary
// falls back to the highlighted code block.
export default function DiffRenderer({ code }: RichFenceProps) {
  if (!code.trim()) {
    return null
  }

  return (
    <div className="my-2 animate-in fade-in slide-in-from-bottom-1 duration-200 motion-reduce:animate-none">
      <FileDiffPanel diff={code} showLineNumbers />
    </div>
  )
}
