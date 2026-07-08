import { useParams } from 'react-router'
import { ConsumptionChart } from '../components/charts/ConsumptionChart'
import { AccountPanel } from '../components/customer/AccountPanel'
import { MeterPanel } from '../components/customer/MeterPanel'
import { SurveyHistoryList } from '../components/customer/SurveyHistoryList'
import { SurveyProfilePanel } from '../components/customer/SurveyProfilePanel'
import { Breadcrumbs } from '../components/layout/Breadcrumbs'
import { Card } from '../components/ui/Card'
import { ErrorPanel } from '../components/ui/ErrorPanel'
import { Skeleton } from '../components/ui/Skeleton'
import { StatusBadge } from '../components/ui/StatusBadge'
import { TimeRangeSelector, useTimeRange } from '../components/ui/TimeRangeSelector'
import { PaymentsTable } from '../components/village/PaymentsTable'
import { useDataProvider } from '../data/DataProviderContext'
import { useAsyncData } from '../hooks/useAsyncData'
import { useI18n } from '../i18n/I18nContext'

const PAYMENTS_SHOWN = 10

export function CustomerPage() {
  const { customerId = '' } = useParams()
  const api = useDataProvider()
  const { t } = useI18n()
  const [range, setRange] = useTimeRange('30d')

  const detail = useAsyncData(() => api.getCustomerDetail(customerId), [api, customerId])
  const consumption = useAsyncData(
    () => api.getCustomerConsumption(customerId, range),
    [api, customerId, range],
  )
  const payments = useAsyncData(
    () => api.listCustomerPayments(customerId, range),
    [api, customerId, range],
  )

  if (detail.error) {
    return (
      <div className="space-y-4">
        <Breadcrumbs
          items={[{ label: t.common.overview, to: '/' }, { label: t.common.customer }]}
        />
        <ErrorPanel error={detail.error} />
      </div>
    )
  }

  if (!detail.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-16 max-w-md" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      </div>
    )
  }

  const { customer, village, meter, surveyResponses } = detail.data

  return (
    <div className="space-y-4">
      <Breadcrumbs
        items={[
          { label: t.common.overview, to: '/' },
          { label: village.name, to: `/villages/${village.id}` },
          { label: customer.fullName },
        ]}
      />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-lg font-semibold">{customer.fullName}</h1>
            <span className="rounded-full bg-page px-2 py-0.5 text-xs font-medium text-ink-secondary">
              {t.customerTypes[customer.customerType]}
            </span>
            <StatusBadge status={meter.status} />
          </div>
          <p className="mt-0.5 text-sm text-ink-secondary">
            {customer.phoneNumber} · {village.name}, {t.common.county(village.county)} ·{' '}
            {customer.id}
          </p>
        </div>
        <TimeRangeSelector value={range} onChange={setRange} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <AccountPanel detail={detail.data} />
        <MeterPanel detail={detail.data} />
        <SurveyProfilePanel detail={detail.data} />
      </div>

      <Card title={t.customerPage.cardConsumption}>
        {consumption.error ? (
          <ErrorPanel error={consumption.error} />
        ) : !consumption.data ? (
          <Skeleton className="h-60" />
        ) : (
          <ConsumptionChart data={consumption.data} range={range} />
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t.customerPage.cardPayments}>
          {payments.error ? (
            <ErrorPanel error={payments.error} />
          ) : !payments.data ? (
            <Skeleton className="h-48" />
          ) : (
            <PaymentsTable
              payments={payments.data.slice(0, PAYMENTS_SHOWN)}
              totalCount={payments.data.length}
            />
          )}
        </Card>
        <Card title={t.customerPage.cardSurveys}>
          <SurveyHistoryList surveys={surveyResponses} />
        </Card>
      </div>
    </div>
  )
}
