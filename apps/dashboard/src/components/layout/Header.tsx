import clsx from 'clsx'
import { Link } from 'react-router'
import { useI18n } from '../../i18n/I18nContext'
import type { Lang } from '../../i18n/translations'

const LANGS: { value: Lang; label: string; name: string }[] = [
  { value: 'en', label: 'EN', name: 'English' },
  { value: 'sw', label: 'SW', name: 'Kiswahili' },
]

export function Header() {
  const { lang, setLang, t } = useI18n()

  return (
    <header className="border-b border-gridline bg-surface">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
        <Link to="/" className="flex items-center gap-3">
          <span
            aria-hidden
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-load text-lg font-bold text-white"
          >
            ⚡
          </span>
          <span>
            <span className="block text-sm font-semibold leading-tight">
              KPLC Microgrid Monitor
            </span>
            <span className="block text-xs leading-tight text-ink-muted">{t.header.subtitle}</span>
          </span>
        </Link>
        <nav className="ml-auto flex items-center gap-2">
          <Link
            to="/"
            className="rounded-md px-3 py-1.5 text-sm font-medium text-ink-secondary hover:bg-page hover:text-ink"
          >
            {t.header.navOverview}
          </Link>
          <div
            className="inline-flex rounded-lg border border-gridline bg-surface p-0.5"
            role="group"
            aria-label={t.header.language}
          >
            {LANGS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setLang(option.value)}
                aria-pressed={lang === option.value}
                title={option.name}
                className={clsx(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  lang === option.value ? 'bg-ink text-white' : 'text-ink-secondary hover:bg-page',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </nav>
      </div>
    </header>
  )
}
