import { Link } from 'react-router'
import type { Payment } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { formatDateTime, formatKes } from '../../lib/format'
import { DataTable, type Column } from '../ui/DataTable'

export function PaymentsTable({
  payments,
  customerNames,
  totalCount,
}: {
  payments: Payment[]
  /** Optional customerId -> display name lookup; names link to profiles. */
  customerNames?: Map<string, string>
  /** When the list is truncated, the full count for the caption. */
  totalCount?: number
}) {
  const { t } = useI18n()
  const columns: Column<Payment>[] = [
    {
      key: 'paidAt',
      header: t.payments.time,
      value: (p) => p.paidAt,
      sortable: true,
      render: (p) => formatDateTime(p.paidAt),
    },
    ...(customerNames
      ? [
          {
            key: 'customer',
            header: t.payments.customer,
            value: (p: Payment) => customerNames.get(p.customerId) ?? p.customerId,
            render: (p: Payment) => (
              <Link
                to={`/customers/${p.customerId}`}
                onClick={(e) => e.stopPropagation()}
                className="text-ink hover:underline"
              >
                {customerNames.get(p.customerId) ?? p.customerId}
              </Link>
            ),
          },
        ]
      : []),
    {
      key: 'ref',
      header: t.payments.ref,
      value: (p) => p.mpesaReference,
      render: (p) => <span className="font-mono text-xs text-ink-secondary">{p.mpesaReference}</span>,
    },
    {
      key: 'kwh',
      header: t.payments.units,
      value: (p) => p.kwhPurchased,
      align: 'right',
      render: (p) => `${p.kwhPurchased.toFixed(1)} kWh`,
    },
    {
      key: 'amount',
      header: t.payments.amount,
      value: (p) => p.amountKes,
      sortable: true,
      align: 'right',
      render: (p) => <span className="font-medium">{formatKes(p.amountKes)}</span>,
    },
  ]

  return (
    <div>
      <DataTable
        columns={columns}
        rows={payments}
        rowKey={(p) => p.id}
        emptyLabel={t.payments.empty}
      />
      {totalCount !== undefined && totalCount > payments.length && (
        <div className="mt-2 text-xs text-ink-muted">
          {t.payments.showingLatest(payments.length, totalCount)}
        </div>
      )}
    </div>
  )
}
