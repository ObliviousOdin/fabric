import { describe, expect, it } from 'vitest'

import { brandText, desktopBrand } from './brand'

describe('desktop brand contract', () => {
  it('uses the Fabric product identity by default', () => {
    expect(desktopBrand).toMatchObject({
      cliName: 'fabric',
      desktopName: 'Fabric',
      productName: 'Fabric',
      vendorName: 'Fabric'
    })
  })

  it('brands product, desktop, CLI, and home-directory copy', () => {
    expect(brandText('Fabric runs Fabric. Try `Fabric gateway` in ~/.hermes/config.yaml.')).toBe(
      'Fabric runs Fabric. Try `fabric gateway` in ~/.fabric/config.yaml.'
    )
  })

  it('preserves third-party Hermes model family names', () => {
    expect(brandText('Nous Hermes 3 and Hermes-4 are model names; Fabric is the app.')).toBe(
      'Nous Hermes 3 and Hermes-4 are model names; Fabric is the app.'
    )
  })
})
