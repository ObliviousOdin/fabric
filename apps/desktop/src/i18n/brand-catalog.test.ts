import { describe, expect, it } from 'vitest'

import { desktopBrand } from '@/brand'

import { brandTranslationCatalog } from './brand-catalog'
import { TRANSLATIONS } from './catalog'

describe('branded desktop translation catalog', () => {
  it('brands static copy in every supported language', () => {
    expect(TRANSLATIONS.en.boot.ready).toBe(`${desktopBrand.desktopName} is ready`)
    expect(TRANSLATIONS.zh.boot.ready).toContain(desktopBrand.desktopName)
    expect(TRANSLATIONS['zh-hant'].boot.ready).toContain(desktopBrand.desktopName)
    expect(TRANSLATIONS.ja.boot.ready).toContain(desktopBrand.desktopName)
  })

  it('brands parameterized copy and customer CLI guidance', () => {
    expect(TRANSLATIONS.en.settings.gateway.connectedTo('https://host.test', '1.2.3')).toContain(
      `${desktopBrand.productName} 1.2.3`
    )
    expect(TRANSLATIONS.en.desktop.handoff.timedOut).toContain('`fabric gateway`')
  })

  it('brands arbitrary nested strings and functions at the catalog boundary', () => {
    const branded = brandTranslationCatalog({
      message: 'Fabric',
      nested: { dynamic: (name: string) => `Fabric welcomes ${name}` }
    } as never) as unknown as {
      message: string
      nested: { dynamic: (name: string) => string }
    }

    expect(branded.message).toBe('Fabric')
    expect(branded.nested.dynamic('Sam')).toBe('Fabric welcomes Sam')
  })
})
