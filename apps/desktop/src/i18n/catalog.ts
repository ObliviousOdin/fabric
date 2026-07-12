import { brandTranslationCatalog } from './brand-catalog'
import { en } from './en'
import { ja } from './ja'
import type { Locale, Translations } from './types'
import { zh } from './zh'
import { zhHant } from './zh-hant'

export const TRANSLATIONS: Record<Locale, Translations> = {
  en: brandTranslationCatalog(en),
  zh: brandTranslationCatalog(zh),
  'zh-hant': brandTranslationCatalog(zhHant),
  ja: brandTranslationCatalog(ja)
}
