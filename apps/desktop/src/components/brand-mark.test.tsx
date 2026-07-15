import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { BrandWordmark } from '@/components/brand-mark'

describe('BrandWordmark', () => {
  it('renders the canonical Fabric wordmark as one accessible image', () => {
    render(<BrandWordmark />)

    const wordmark = screen.getByRole('img', { name: 'Fabric' })
    const [lightAsset, darkAsset] = screen.getAllByRole('presentation')

    expect(wordmark.getAttribute('aria-label')).toBe('Fabric')
    expect(lightAsset.getAttribute('src')).toBeTruthy()
    expect(darkAsset.getAttribute('src')).toBeTruthy()
    expect(lightAsset.getAttribute('src')).not.toBe(darkAsset.getAttribute('src'))
    expect(lightAsset.className).toContain('dark:hidden')
    expect(darkAsset.className).toContain('dark:block')
  })
})
