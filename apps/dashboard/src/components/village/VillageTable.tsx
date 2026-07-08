import { useMemo } from 'react'
import { useNavigate } from 'react-router'
import type { VillageSummary } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { formatKesCompact, formatKwh, formatNumber, formatPct } from '../../lib/format'
import { DataTable, type Column } from '../ui/DataTable'
import { StatusBadge } from '../ui/StatusBadge'

export function VillageTable({ summaries }: { summaries: VillageSummary[] }) {
  const navigate = useNavigate()
  const { t } = useI18n()

  const columns = useMemo<Column<VillageSummary>[]>(
    () => [
      {
        key: 'name',
        header: t.villageTable.village,
        value: (s) => s.village.name,
        sortable: true,
        render: (s) => (
          <div>
            <div className="font-medium text-ink">{s.village.name}</div>
            <div className="text-xs text-ink-muted">{t.common.county(s.village.county)}</div>
          </div>
        ),
      },
      {
        key: 'status',
        header: t.villageTable.status,
        value: (s) => s.village.status,
        sortable: true,
        render: (s) => <StatusBadge status={s.village.status} />,
      },
      {
        key: 'customers',
        header: t.villageTable.customers,
        value: (s) => s.customerCount,
        sortable: true,
        align: 'right',
        render: (s) => formatNumber(s.customerCount),
      },
      {
        key: 'soc',
        header: t.villageTable.socNow,
        value: (s) => s.currentSocPct,
        sortable: true,
        align: 'right',
        render: (s) => formatPct(s.currentSocPct),
      },
      {
        key: 'pvToday',
        header: t.villageTable.pvToday,
        value: (s) => s.pvTodayKwh,
        sortable: true,
        align: 'right',
        render: (s) => formatKwh(s.pvTodayKwh),
      },
      {
        key: 'uptime',
        header: t.villageTable.uptime30d,
        value: (s) => s.uptimePct30d,
        sortable: true,
        align: 'right',
        render: (s) => `${s.uptimePct30d.toFixed(1)}%`,
      },
      {
        key: 'revenue',
        header: t.villageTable.revenueMtd,
        value: (s) => s.revenueMtdKes,
        sortable: true,
        align: 'right',
        render: (s) => formatKesCompact(s.revenueMtdKes),
      },
      {
        key: 'arrears',
        header: t.villageTable.inArrears,
        value: (s) => s.customersInArrears,
        sortable: true,
        align: 'right',
        render: (s) =>
          s.customersInArrears > 0 ? (
            <span className="font-medium text-status-critical">{s.customersInArrears}</span>
          ) : (
            '0'
          ),
      },
    ],
    [t],
  )

  return (
    <DataTable
      columns={columns}
      rows={summaries}
      rowKey={(s) => s.village.id}
      onRowClick={(s) => navigate(`/villages/${s.village.id}`)}
      initialSort={{ key: 'name', dir: 'asc' }}
    />
  )
}
