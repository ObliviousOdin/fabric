import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { Locale, Translations } from "./types";
import { I18nContext, type I18nContextValue } from "./use-i18n";
import { LOCALE_META } from "./locale-meta";
import { en } from "./en";

type DeferredLocale = Exclude<Locale, "en">;

// English is the boot language. Every other locale is a route-independent
// async chunk, so the default shell does not parse roughly 500 KB of
// translations it will never use. Loaded dictionaries stay cached for later
// switches; a failed offline chunk keeps the current readable language.
const TRANSLATION_LOADERS: Record<DeferredLocale, () => Promise<Translations>> =
  {
    zh: () => import("./zh").then(({ zh }) => zh),
    "zh-hant": () => import("./zh-hant").then(({ zhHant }) => zhHant),
    ja: () => import("./ja").then(({ ja }) => ja),
    de: () => import("./de").then(({ de }) => de),
    es: () => import("./es").then(({ es }) => es),
    fr: () => import("./fr").then(({ fr }) => fr),
    tr: () => import("./tr").then(({ tr }) => tr),
    uk: () => import("./uk").then(({ uk }) => uk),
    af: () => import("./af").then(({ af }) => af),
    ko: () => import("./ko").then(({ ko }) => ko),
    it: () => import("./it").then(({ it }) => it),
    ga: () => import("./ga").then(({ ga }) => ga),
    pt: () => import("./pt").then(({ pt }) => pt),
    ru: () => import("./ru").then(({ ru }) => ru),
    hu: () => import("./hu").then(({ hu }) => hu),
  };

const TRANSLATION_CACHE: Partial<Record<Locale, Translations>> = { en };
const STORAGE_KEY = "fabric-locale";

function isLocale(value: string): value is Locale {
  return Object.hasOwn(LOCALE_META, value);
}

async function loadTranslations(locale: Locale): Promise<Translations> {
  const cached = TRANSLATION_CACHE[locale];
  if (cached) return cached;
  if (locale === "en") return en;

  const loaded = await TRANSLATION_LOADERS[locale]();
  TRANSLATION_CACHE[locale] = loaded;
  return loaded;
}

function getInitialLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && isLocale(stored)) {
      return stored;
    }
  } catch {
    // SSR or privacy mode
  }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [requestedLocale, setRequestedLocale] =
    useState<Locale>(getInitialLocale);
  const initialTranslations = TRANSLATION_CACHE[requestedLocale];
  const [locale, setLocaleState] = useState<Locale>(() =>
    initialTranslations ? requestedLocale : "en",
  );
  const [translations, setTranslations] = useState<Translations>(
    () => initialTranslations ?? en,
  );

  useEffect(() => {
    let active = true;

    void loadTranslations(requestedLocale)
      .then((next) => {
        if (!active) return;
        setTranslations(next);
        setLocaleState(requestedLocale);
      })
      .catch(() => {
        // The currently rendered dictionary remains usable when an optional
        // locale chunk cannot be fetched (for example after going offline).
        // Reset the request so choosing that locale again can retry without a
        // full page reload; the persisted preference remains intact.
        if (active) setRequestedLocale(locale);
      });

    return () => {
      active = false;
    };
  }, [locale, requestedLocale]);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((l: Locale) => {
    setRequestedLocale(l);
    const cached = TRANSLATION_CACHE[l];
    if (cached) {
      setTranslations(cached);
      setLocaleState(l);
    }
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // ignore
    }
  }, []);

  const value: I18nContextValue = {
    locale,
    setLocale,
    t: translations,
  };

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
