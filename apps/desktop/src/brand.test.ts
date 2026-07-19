import { describe, expect, it } from 'vitest'

import { desktopBrand } from './brand'

describe('desktop brand contract', () => {
  it('uses the Fabric product identity by default', () => {
    expect(desktopBrand).toMatchObject({
      cliName: 'fabric',
      desktopName: 'Fabric',
      productName: 'Fabric',
      vendorName: 'Fabric'
    })
  })
})
