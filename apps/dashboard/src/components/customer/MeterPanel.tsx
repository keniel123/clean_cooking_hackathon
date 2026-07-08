import type { CustomerDetail } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import { formatDate, timeAgo } from '../../lib/format'
import { Card } from '../ui/Card'
import { StatusBadge } from '../ui/StatusBadge'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5">
      <dt className="text-sm text-ink-secondary">{label}</dt>
      <dd className="text-sm font-medium text-ink">{children}</dd>
    </div>
  )
}

export function MeterPanel({ detail }: { detail: CustomerDetail }) {
  const { t } = useI18n()
  const { meter } = detail
  return (
    <Card title={t.customerPage.cardMeter}>
      <dl className="divide-y divide-gridline/60">
        <Row label={t.customerPage.meterSerial}>
          <span className="font-mono text-xs">{meter.serialNumber}</span>
        </Row>
        <Row label={t.customerPage.status}>
          <StatusBadge status={meter.status} />
        </Row>
        <Row label={t.customerPage.installed}>{formatDate(meter.installedAt)}</Row>
        <Row label={t.customerPage.lastSeen}>{timeAgo(meter.lastSeenAt)}</Row>
        <Row label={t.customerPage.location}>
          <span className="tabular-nums">
            {meter.latitude.toFixed(4)}, {meter.longitude.toFixed(4)}
          </span>
        </Row>
      </dl>
    </Card>
  )
}
