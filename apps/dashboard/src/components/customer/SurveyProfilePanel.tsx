import type { CustomerDetail } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { Card } from '../ui/Card'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5">
      <dt className="text-sm text-ink-secondary">{label}</dt>
      <dd className="text-sm font-medium text-ink">{value}</dd>
    </div>
  )
}

/** Profile metadata collected via SMS surveys. */
export function SurveyProfilePanel({ detail }: { detail: CustomerDetail }) {
  const { t } = useI18n()
  const { customer } = detail
  return (
    <Card title={t.customerPage.cardSurveyProfile}>
      <dl className="divide-y divide-gridline/60">
        <Row
          label={t.customerPage.userType}
          value={t.customerTypes[customer.customerType]}
        />
        {customer.householdSize !== null && (
          <Row label={t.customerPage.householdSize} value={String(customer.householdSize)} />
        )}
        {customer.occupation && (
          <Row label={t.customerPage.occupation} value={customer.occupation} />
        )}
      </dl>
      <div className="mt-3 border-t border-gridline/60 pt-3">
        <div className="mb-1.5 text-sm text-ink-secondary">{t.customerPage.appliances}</div>
        {customer.appliancesOwned.length === 0 ? (
          <div className="text-sm text-ink-muted">{t.customerPage.notSurveyed}</div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {customer.appliancesOwned.map((appliance) => (
              <span
                key={appliance}
                className="rounded-full bg-page px-2 py-0.5 text-xs font-medium text-ink-secondary"
              >
                {appliance}
              </span>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}
