import { useNavigate } from 'react-router'
import { RevenueChart } from '../components/charts/RevenueChart'
import { SiteMap } from '../components/map/SiteMap'
import { Card } from '../components/ui/Card'
import { ErrorPanel } from '../components/ui/ErrorPanel'
import { KpiCard } from '../components/ui/KpiCard'
import { KpiSkeletonRow, Skeleton } from '../components/ui/Skeleton'
import { TimeRangeSelector, useTimeRange } from '../components/ui/TimeRangeSelector'
import { VillageTable } from '../components/village/VillageTable'
import { useDataProvider } from '../data/DataProviderContext'
import { useAsyncData } from '../hooks/useAsyncData'
import { useI18n } from '../i18n/I18nContext'
import { formatKesCompact, formatKwh, formatNumber, formatPct } from '../lib/format'

export function OverviewPage() {
  const api = useDataProvider()
  const navigate = useNavigate()
  const { t } = useI18n()
  const [range, setRange] = useTimeRange('30d')

  const kpis = useAsyncData(() => api.getFleetKpis(), [api])
  const summaries = useAsyncData(() => api.listVillageSummaries(), [api])
  const revenue = useAsyncData(() => api.getFleetRevenueSeries(range), [api, range])

  const degraded = summaries.data?.filter((s) => s.village.status === 'degraded').length ?? 0
  const offline = summaries.data?.filter((s) => s.village.status === 'offline').length ?? 0

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">{t.overview.title}</h1>

      {kpis.error ? (
        <ErrorPanel error={kpis.error} />
      ) : !kpis.data ? (
        <KpiSkeletonRow />
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <KpiCard
            label={t.overview.kpiVillagesOperational}
            value={`${kpis.data.operationalVillages}/${kpis.data.totalVillages}`}
            sub={
              degraded + offline > 0
                ? [
                    degraded ? t.overview.nDegraded(degraded) : '',
                    offline ? t.overview.nOffline(offline) : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')
                : t.overview.allHealthy
            }
            tone={offline > 0 ? 'bad' : degraded > 0 ? 'warn' : 'good'}
          />
          <KpiCard
            label={t.overview.kpiCustomers}
            value={formatNumber(kpis.data.totalCustomers)}
            sub={t.overview.kwpInstalled(formatNumber(kpis.data.totalPvCapacityKwp))}
          />
          <KpiCard label={t.overview.kpiPvToday} value={formatKwh(kpis.data.pvTodayKwh)} />
          <KpiCard
            label={t.overview.kpiAvgSoc}
            value={formatPct(kpis.data.avgSocPct)}
            sub={t.overview.avgUptime(`${kpis.data.avgUptimePct30d.toFixed(1)}%`)}
          />
          <KpiCard
            label={t.overview.kpiRevenueMtd}
            value={formatKesCompact(kpis.data.revenueMtdKes)}
            sub={t.overview.mpesaCollections}
          />
          <KpiCard
            label={t.overview.kpiTotalArrears}
            value={formatKesCompact(kpis.data.totalArrearsKes)}
            sub={t.overview.outstandingBalances}
            tone="bad"
          />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t.overview.cardSites} className="p-4">
          <div className="h-90 overflow-hidden rounded-lg">
            {summaries.error ? (
              <ErrorPanel error={summaries.error} />
            ) : !summaries.data ? (
              <Skeleton className="h-full" />
            ) : (
              <SiteMap
                sites={summaries.data}
                onSelect={(villageId) => navigate(`/villages/${villageId}`)}
              />
            )}
          </div>
        </Card>

        <Card
          title={t.overview.cardRevenue}
          actions={<TimeRangeSelector value={range} onChange={setRange} />}
        >
          {revenue.error ? (
            <ErrorPanel error={revenue.error} />
          ) : !revenue.data ? (
            <Skeleton className="h-70" />
          ) : (
            <RevenueChart data={revenue.data} range={range} />
          )}
        </Card>
      </div>

      <Card title={t.overview.cardVillages}>
        {summaries.error ? (
          <ErrorPanel error={summaries.error} />
        ) : !summaries.data ? (
          <Skeleton className="h-64" />
        ) : (
          <VillageTable summaries={summaries.data} />
        )}
      </Card>
    </div>
  )
}
