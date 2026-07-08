import { Link } from 'react-router'
import type { CustomerRow } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { formatKes } from '../../lib/format'
import { EmptyState } from '../ui/EmptyState'
import { StatusBadge } from '../ui/StatusBadge'

export function ArrearsList({ rows }: { rows: CustomerRow[] }) {
  const { t } = useI18n()
  const inArrears = rows
    .filter((r) => r.customer.arrearsKes > 0)
    .sort((a, b) => b.customer.arrearsKes - a.customer.arrearsKes)

  if (inArrears.length === 0) return <EmptyState message={t.village.noArrears} />

  return (
    <ul className="max-h-72 divide-y divide-gridline/60 overflow-y-auto">
      {inArrears.map((r) => (
        <li key={r.customer.id} className="flex items-center gap-3 py-2">
          <div className="min-w-0 flex-1">
            <Link
              to={`/customers/${r.customer.id}`}
              className="block truncate text-sm font-medium text-ink hover:underline"
            >
              {r.customer.fullName}
            </Link>
            <div className="text-xs text-ink-muted">{r.customer.phoneNumber}</div>
          </div>
          <StatusBadge status={r.meterStatus} />
          <div className="w-24 text-right text-sm font-medium tabular-nums text-status-critical">
            {formatKes(r.customer.arrearsKes)}
          </div>
        </li>
      ))}
    </ul>
  )
}
