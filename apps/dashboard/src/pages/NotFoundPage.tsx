import { Link } from 'react-router'
import { useI18n } from '../i18n/I18nContext'

export function NotFoundPage() {
  const { t } = useI18n()
  return (
    <div className="py-16 text-center">
      <div className="text-3xl font-semibold">{t.notFound.title}</div>
      <p className="mt-2 text-sm text-ink-secondary">{t.notFound.body}</p>
      <Link
        to="/"
        className="mt-4 inline-block rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-ink/85"
      >
        {t.notFound.back}
      </Link>
    </div>
  )
}
