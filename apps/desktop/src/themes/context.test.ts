import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resolvedSemanticThemes } from '../../../design-system/dist/tokens.js'

const desktopWindow = window as unknown as { fabricDesktop?: Window['fabricDesktop'] }

async function bootTheme(skin: string, mode: 'light' | 'dark') {
  const setTitleBarTheme = vi.fn()

  window.localStorage.setItem('hermes-desktop-theme-v2', skin)
  window.localStorage.setItem('hermes-desktop-mode-v1', mode)
  desktopWindow.fabricDesktop = { setTitleBarTheme } as unknown as Window['fabricDesktop']

  await import('./context')

  return setTitleBarTheme
}

beforeEach(() => {
  vi.resetModules()
  window.localStorage.clear()
  document.documentElement.removeAttribute('class')
  document.documentElement.removeAttribute('style')
  document.documentElement.removeAttribute('data-fabric-color-scheme')
  document.documentElement.removeAttribute('data-fabric-mode')
  document.documentElement.removeAttribute('data-fabric-theme')
})

afterEach(() => {
  delete desktopWindow.fabricDesktop
  document.querySelectorAll('link[data-fabric-theme-font]').forEach(link => link.remove())
})

describe('desktop theme boot paint', () => {
  it('applies the canonical Fabric surfaces without legacy color blending', async () => {
    const setTitleBarTheme = await bootTheme('fabric', 'light')
    const semantic = resolvedSemanticThemes.light
    const root = document.documentElement

    expect(root.dataset.fabricColorScheme).toBe('light')
    expect(root.dataset.fabricTheme).toBe('fabric')
    expect(root.style.getPropertyValue('--theme-neutral-chrome')).toBe(semantic.canvas)
    expect(root.style.getPropertyValue('--theme-neutral-sidebar')).toBe(semantic.surface)
    expect(root.style.getPropertyValue('--theme-neutral-card')).toBe(semantic.surface)
    expect(root.style.getPropertyValue('--theme-mix-chrome')).toBe('100%')
    expect(root.style.getPropertyValue('--theme-mix-card')).toBe('100%')
    expect(root.style.getPropertyValue('--theme-mix-elevated')).toBe('100%')
    expect(setTitleBarTheme).toHaveBeenCalledWith({ background: semantic.canvas, foreground: semantic.text })
  })

  it('preserves the established blend treatment for non-Fabric themes', async () => {
    const setTitleBarTheme = await bootTheme('midnight', 'dark')
    const root = document.documentElement

    expect(root.dataset.fabricColorScheme).toBe('dark')
    expect(root.dataset.fabricTheme).toBe('midnight')
    expect(root.style.getPropertyValue('--theme-neutral-chrome')).toBe('#0d0d0e')
    expect(root.style.getPropertyValue('--theme-mix-chrome')).toBe('74%')
    expect(root.style.getPropertyValue('--theme-mix-card')).toBe('38%')
    expect(root.style.getPropertyValue('--theme-mix-elevated')).toBe('46%')
    expect(setTitleBarTheme).toHaveBeenCalledWith(
      expect.objectContaining({ background: expect.not.stringMatching(/^#08081c$/i), foreground: '#ddd6ff' })
    )
  })
})
