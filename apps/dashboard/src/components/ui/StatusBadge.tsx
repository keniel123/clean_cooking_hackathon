import clsx from 'clsx'
import type { MeterStatus, VillageStatus } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'

type Status = VillageStatus | MeterStatus

const CONFIG: Record<Status, { dot: string; text: string; bg: string }> = {
  operational: { dot: 'bg-status-good', text: 'text-status-good-text', bg: 'bg-status-good/10' },
  online: { dot: 'bg-status-good', text: 'text-status-good-text', bg: 'bg-status-good/10' },
  degraded: { dot: 'bg-status-warning', text: 'text-ink-secondary', bg: 'bg-status-warning/15' },
  offline: { dot: 'bg-status-critical', text: 'text-status-critical', bg: 'bg-status-critical/10' },
  disconnected: { dot: 'bg-ink-muted', text: 'text-ink-secondary', bg: 'bg-ink-muted/10' },
}

export function StatusBadge({ status }: { status: Status }) {
  const { t } = useI18n()
  const c = CONFIG[status]
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium',
        c.text,
        c.bg,
      )}
    >
      <span aria-hidden className={clsx('h-1.5 w-1.5 rounded-full', c.dot)} />
      {t.status[status]}
    </span>
  )
}
