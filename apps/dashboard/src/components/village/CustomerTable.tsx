import { useMemo } from 'react'
import { useNavigate } from 'react-router'
import type { CustomerRow } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { formatDate, formatKes } from '../../lib/format'
import { DataTable, type Column } from '../ui/DataTable'
import { StatusBadge } from '../ui/StatusBadge'

export function CustomerTable({ rows }: { rows: CustomerRow[] }) {
  const navigate = useNavigate()
  const { t } = useI18n()

  const columns = useMemo<Column<CustomerRow>[]>(
    () => [
      {
        key: 'name',
        header: t.customerTable.customer,
        value: (r) => r.customer.fullName,
        sortable: true,
        render: (r) => (
          <div>
            <div className="font-medium text-ink">{r.customer.fullName}</div>
            <div className="text-xs text-ink-muted">{r.customer.phoneNumber}</div>
          </div>
        ),
      },
      {
        key: 'type',
        header: t.customerTable.type,
        value: (r) => r.customer.customerType,
        sortable: true,
        render: (r) => t.customerTypes[r.customer.customerType],
      },
      {
        key: 'meter',
        header: t.customerTable.meter,
        value: (r) => r.meterStatus,
        sortable: true,
        render: (r) => <StatusBadge status={r.meterStatus} />,
      },
      {
        key: 'balance',
        header: t.customerTable.balance,
        value: (r) => r.customer.accountBalanceKes,
        sortable: true,
        align: 'right',
        render: (r) => formatKes(r.customer.accountBalanceKes),
      },
      {
        key: 'arrears',
        header: t.customerTable.arrears,
        value: (r) => r.customer.arrearsKes,
        sortable: true,
        align: 'right',
        render: (r) =>
          r.customer.arrearsKes > 0 ? (
            <span className="font-medium text-status-critical">
              {formatKes(r.customer.arrearsKes)}
            </span>
          ) : (
            '—'
          ),
      },
      {
        key: 'connected',
        header: t.customerTable.connected,
        value: (r) => r.customer.connectedAt,
        sortable: true,
        align: 'right',
        render: (r) => formatDate(r.customer.connectedAt),
      },
    ],
    [t],
  )

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(r) => r.customer.id}
      onRowClick={(r) => navigate(`/customers/${r.customer.id}`)}
      searchText={(r) => `${r.customer.fullName} ${r.customer.phoneNumber} ${r.customer.id}`}
      searchPlaceholder={t.customerTable.searchPlaceholder}
      emptyLabel={t.customerTable.empty}
      initialSort={{ key: 'name', dir: 'asc' }}
    />
  )
}
