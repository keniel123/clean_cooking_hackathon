import type { CustomerDetail } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { formatKes } from '../../lib/format'
import { Card } from '../ui/Card'

function Row({ label, value, critical }: { label: string; value: string; critical?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-sm text-ink-secondary">{label}</dt>
      <dd
        className={
          critical
            ? 'text-sm font-semibold tabular-nums text-status-critical'
            : 'text-sm font-medium tabular-nums text-ink'
        }
      >
        {value}
      </dd>
    </div>
  )
}

export function AccountPanel({ detail }: { detail: CustomerDetail }) {
  const { t } = useI18n()
  const { customer, tariff } = detail
  return (
    <Card title={t.customerPage.cardAccount}>
      <div className="mb-3">
        <div className="text-xs font-medium text-ink-secondary">{t.customerPage.paygBalance}</div>
        <div className="mt-0.5 text-2xl font-semibold text-ink">
          {formatKes(customer.accountBalanceKes)}
        </div>
        {customer.arrearsKes > 0 && (
          <div className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-status-critical/10 px-2 py-0.5 text-xs font-medium text-status-critical">
            <span aria-hidden>▲</span>
            {t.customerPage.inArrearsChip(formatKes(customer.arrearsKes))}
          </div>
        )}
      </div>
      <dl className="divide-y divide-gridline/60 border-t border-gridline/60">
        <Row label={t.customerPage.tariffPlan} value={tariff.name} />
        <Row label={t.customerPage.pricePerKwh} value={formatKes(tariff.pricePerKwhKes)} />
        <Row label={t.customerPage.dailyCharge} value={formatKes(tariff.dailyServiceChargeKes)} />
        <Row label={t.customerPage.loadLimit} value={`${tariff.loadLimitW.toLocaleString()} W`} />
        <Row
          label={t.customerPage.arrears}
          value={customer.arrearsKes > 0 ? formatKes(customer.arrearsKes) : t.customerPage.none}
          critical={customer.arrearsKes > 0}
        />
      </dl>
    </Card>
  )
}
