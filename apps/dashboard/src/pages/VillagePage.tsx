import { useMemo } from 'react'
import { useParams } from 'react-router'
import { EnergyChart } from '../components/charts/EnergyChart'
import { RevenueChart } from '../components/charts/RevenueChart'
import { SocChart } from '../components/charts/SocChart'
import { Breadcrumbs } from '../components/layout/Breadcrumbs'
import { Card } from '../components/ui/Card'
import { ErrorPanel } from '../components/ui/ErrorPanel'
import { KpiCard } from '../components/ui/KpiCard'
import { KpiSkeletonRow, Skeleton } from '../components/ui/Skeleton'
import { StatusBadge } from '../components/ui/StatusBadge'
import { TimeRangeSelector, useTimeRange } from '../components/ui/TimeRangeSelector'
import { ArrearsList } from '../components/village/ArrearsList'
import { CustomerTable } from '../components/village/CustomerTable'
import { PaymentsTable } from '../components/village/PaymentsTable'
import { useDataProvider } from '../data/DataProviderContext'
import { useAsyncData } from '../hooks/useAsyncData'
import { useI18n } from '../i18n/I18nContext'
import { formatDate, formatKesCompact, formatKw, formatKwh, formatPct } from '../lib/format'

const PAYMENTS_SHOWN = 12

export function VillagePage() {
  const { villageId = '' } = useParams()
  const api = useDataProvider()
  const { t } = useI18n()
  const [range, setRange] = useTimeRange('7d')

  const summary = useAsyncData(() => api.getVillageSummary(villageId), [api, villageId])
  const energy = useAsyncData(() => api.getVillageEnergySeries(villageId, range), [api, villageId, range])
  const revenue = useAsyncData(() => api.getVillageRevenueSeries(villageId, range), [api, villageId, range])
  const payments = useAsyncData(() => api.listVillagePayments(villageId, range), [api, villageId, range])
  const customers = useAsyncData(() => api.listCustomers(villageId), [api, villageId])

  const customerNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const row of customers.data ?? []) map.set(row.customer.id, row.customer.fullName)
    return map
  }, [customers.data])

  if (summary.error) {
    return (
      <div className="space-y-4">
        <Breadcrumbs
          items={[{ label: t.common.overview, to: '/' }, { label: t.common.village }]}
        />
        <ErrorPanel error={summary.error} />
      </div>
    )
  }

  const village = summary.data?.village

  return (
    <div className="space-y-4">
      <Breadcrumbs
        items={[
          { label: t.common.overview, to: '/' },
          { label: village?.name ?? t.common.village },
        ]}
      />

      {!summary.data || !village ? (
        <Skeleton className="h-16 max-w-md" />
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold">{village.name}</h1>
              <StatusBadge status={village.status} />
            </div>
            <p className="mt-0.5 text-sm text-ink-secondary">
              {[
                t.common.county(village.county),
                t.village.commissioned(formatDate(village.commissionedAt)),
                t.village.pvSpec(village.pvCapacityKwp),
                t.village.batterySpec(village.batteryCapacityKwh),
                t.village.inverterSpec(village.inverterCapacityKw),
              ].join(' · ')}
            </p>
          </div>
          <TimeRangeSelector value={range} onChange={setRange} />
        </div>
      )}

      {!summary.data ? (
        <KpiSkeletonRow />
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <KpiCard label={t.village.kpiSocNow} value={formatPct(summary.data.currentSocPct)} />
          <KpiCard label={t.village.kpiLoadNow} value={formatKw(summary.data.currentLoadKw)} />
          <KpiCard label={t.village.kpiPvToday} value={formatKwh(summary.data.pvTodayKwh)} />
          <KpiCard
            label={t.village.kpiUptime}
            value={`${summary.data.uptimePct30d.toFixed(1)}%`}
            tone={summary.data.uptimePct30d < 97 ? 'warn' : 'good'}
            sub={summary.data.uptimePct30d < 97 ? t.village.belowTarget : t.village.meetsTarget}
          />
          <KpiCard
            label={t.village.kpiRevenueMtd}
            value={formatKesCompact(summary.data.revenueMtdKes)}
            sub={t.overview.mpesaCollections}
          />
          <KpiCard
            label={t.village.kpiInArrears}
            value={String(summary.data.customersInArrears)}
            sub={t.village.ofNCustomers(summary.data.customerCount)}
            tone={summary.data.customersInArrears > 0 ? 'bad' : 'good'}
          />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t.village.cardEnergy}>
          {energy.error ? (
            <ErrorPanel error={energy.error} />
          ) : !energy.data ? (
            <Skeleton className="h-70" />
          ) : (
            <EnergyChart data={energy.data} range={range} />
          )}
        </Card>
        <Card title={t.village.cardSoc}>
          {energy.error ? (
            <ErrorPanel error={energy.error} />
          ) : !energy.data ? (
            <Skeleton className="h-70" />
          ) : (
            <SocChart data={energy.data} range={range} />
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t.village.cardRevenue}>
          {revenue.error ? (
            <ErrorPanel error={revenue.error} />
          ) : !revenue.data ? (
            <Skeleton className="h-70" />
          ) : (
            <RevenueChart data={revenue.data} range={range} />
          )}
        </Card>
        <Card title={t.village.cardArrears}>
          {customers.error ? (
            <ErrorPanel error={customers.error} />
          ) : !customers.data ? (
            <Skeleton className="h-70" />
          ) : (
            <ArrearsList rows={customers.data} />
          )}
        </Card>
      </div>

      <Card title={t.village.cardPayments}>
        {payments.error ? (
          <ErrorPanel error={payments.error} />
        ) : !payments.data ? (
          <Skeleton className="h-48" />
        ) : (
          <PaymentsTable
            payments={payments.data.slice(0, PAYMENTS_SHOWN)}
            customerNames={customerNames}
            totalCount={payments.data.length}
          />
        )}
      </Card>

      <Card title={t.village.cardCustomers}>
        {customers.error ? (
          <ErrorPanel error={customers.error} />
        ) : !customers.data ? (
          <Skeleton className="h-64" />
        ) : (
          <CustomerTable rows={customers.data} />
        )}
      </Card>
    </div>
  )
}
