import { brandText } from '@/brand'

import type { Translations } from './types'

type TranslationFunction = (...args: never[]) => string

function brandValue(value: unknown): unknown {
  if (typeof value === 'string') {
    return brandText(value)
  }

  if (typeof value === 'function') {
    return (...args: never[]) => brandText((value as TranslationFunction)(...args))
  }

  if (Array.isArray(value)) {
    return value.map(brandValue)
  }

  if (typeof value === 'object' && value !== null) {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, brandValue(child)]))
  }

  return value
}

/**
 * Brand a complete locale, including strings returned by parameterized
 * translations. Keeping this at the catalog boundary means every consumer
 * (`useI18n` and the non-React `translateNow`) observes the same identity.
 */
export function brandTranslationCatalog(translations: Translations): Translations {
  return brandValue(translations) as Translations
}
