import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setFormatLocale } from '../lib/format'
import { MESSAGES, type Lang, type Messages } from './translations'

const STORAGE_KEY = 'kplc-lang'

interface I18n {
  lang: Lang
  setLang: (lang: Lang) => void
  t: Messages
}

const I18nContext = createContext<I18n | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() =>
    localStorage.getItem(STORAGE_KEY) === 'sw' ? 'sw' : 'en',
  )

  // bind the shared number/date formatters to the active language before
  // children render (idempotent, so safe to run every render)
  setFormatLocale(lang)

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const value = useMemo<I18n>(
    () => ({
      lang,
      setLang: (l: Lang) => {
        localStorage.setItem(STORAGE_KEY, l)
        setLangState(l)
      },
      t: MESSAGES[lang],
    }),
    [lang],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18n {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used inside <I18nProvider>')
  return ctx
}
