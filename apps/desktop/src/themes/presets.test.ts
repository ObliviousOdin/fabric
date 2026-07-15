import { describe, expect, it } from 'vitest'

import { resolvedSemanticThemes } from '../../../design-system/dist/tokens.js'

import { BUILTIN_THEME_LIST, DEFAULT_TYPOGRAPHY, EMOJI_FALLBACK, fabricTheme } from './presets'

// #40364: none of the UI text/mono fonts carry emoji glyphs, so every font
// stack must end with a color-emoji fallback or emoji render as tofu on
// platforms whose default font lacks them (e.g. Linux).
describe('theme typography emoji fallback (#40364)', () => {
  const stacks: Array<[string, string]> = [
    ['DEFAULT_TYPOGRAPHY.fontSans', DEFAULT_TYPOGRAPHY.fontSans],
    ['DEFAULT_TYPOGRAPHY.fontMono', DEFAULT_TYPOGRAPHY.fontMono],
    // A theme may override only fontMono (fontSans then falls back to the
    // default, which already carries the emoji stack), so skip undefined.
    ...BUILTIN_THEME_LIST.flatMap(theme =>
      (
        [
          [`${theme.name}.fontSans`, theme.typography?.fontSans],
          [`${theme.name}.fontMono`, theme.typography?.fontMono]
        ] as Array<[string, string | undefined]>
      ).filter((entry): entry is [string, string] => typeof entry[1] === 'string')
    )
  ]

  it.each(stacks)('%s includes a color-emoji font', (_label, stack) => {
    expect(stack).toMatch(/Apple Color Emoji|Segoe UI Emoji|Noto Color Emoji|(^|,\s*)emoji\b/)
  })

  it('EMOJI_FALLBACK lists the major platform emoji fonts', () => {
    expect(EMOJI_FALLBACK).toContain('Apple Color Emoji')
    expect(EMOJI_FALLBACK).toContain('Segoe UI Emoji')
    expect(EMOJI_FALLBACK).toContain('Noto Color Emoji')
  })
})

describe('Fabric theme design-system contract', () => {
  it.each(['light', 'dark'] as const)('%s semantic roles are fully resolved before desktop consumption', appearance => {
    expect(Object.values(resolvedSemanticThemes[appearance])).toEqual(
      expect.arrayContaining([expect.stringMatching(/^#[0-9a-f]{6}$/i)])
    )

    for (const value of Object.values(resolvedSemanticThemes[appearance])) {
      expect(value).toMatch(/^#[0-9a-f]{6}$/i)
      expect(value).not.toContain('{')
    }
  })

  it.each([
    ['light', fabricTheme.colors],
    ['dark', fabricTheme.darkColors]
  ] as const)('%s maps the desktop shell onto shared semantic roles', (appearance, desktop) => {
    const semantic = resolvedSemanticThemes[appearance]

    expect(desktop).toMatchObject({
      background: semantic.canvas,
      foreground: semantic.text,
      card: semantic.surface,
      mutedForeground: semantic.textMuted,
      primary: semantic.action,
      ring: semantic.focus,
      border: semantic.border,
      destructive: semantic.danger,
      sidebarBackground: semantic.surface,
      userBubble: semantic.surfaceBrand
    })
  })

  it('uses local system typography without a remote brand font', () => {
    expect(fabricTheme.typography).toEqual(DEFAULT_TYPOGRAPHY)
    expect(fabricTheme.typography?.fontUrl).toBeUndefined()
  })
})
