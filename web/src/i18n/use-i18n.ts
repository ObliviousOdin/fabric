import { createContext, useContext } from "react";
import type { Locale, Translations } from "./types";
import { en } from "./en";

// The context object and hook live outside context.tsx so that file exports
// only components (Fast Refresh requirement) — a mixed-export provider file
// forces a full reload on every i18n edit.

export interface I18nContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: Translations;
}

export const I18nContext = createContext<I18nContextValue>({
  locale: "en",
  setLocale: () => {},
  t: en,
});

export function useI18n() {
  return useContext(I18nContext);
}
