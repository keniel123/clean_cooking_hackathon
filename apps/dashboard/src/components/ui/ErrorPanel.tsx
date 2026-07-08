import { useI18n } from '../../i18n/I18nContext'

export function ErrorPanel({ error }: { error: Error }) {
  const { t } = useI18n()
  return (
    <div
      role="alert"
      className="rounded-xl border border-status-critical/30 bg-status-critical/5 p-4 text-sm"
    >
      <div className="font-semibold text-status-critical">{t.common.errorTitle}</div>
      <div className="mt-1 text-ink-secondary">{error.message}</div>
    </div>
  )
}
