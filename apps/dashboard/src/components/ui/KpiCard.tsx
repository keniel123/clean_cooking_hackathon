import clsx from 'clsx'

export type KpiTone = 'default' | 'good' | 'warn' | 'bad'

const SUB_TONE: Record<KpiTone, string> = {
  default: 'text-ink-muted',
  good: 'text-status-good-text',
  warn: 'text-status-serious',
  bad: 'text-status-critical',
}

export function KpiCard({
  label,
  value,
  unit,
  sub,
  tone = 'default',
}: {
  label: string
  value: string
  unit?: string
  sub?: string
  tone?: KpiTone
}) {
  return (
    <div className="rounded-xl border border-gridline bg-surface p-4 shadow-xs">
      <div className="text-xs font-medium text-ink-secondary">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-ink">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-ink-muted">{unit}</span>}
      </div>
      {sub && <div className={clsx('mt-0.5 text-xs', SUB_TONE[tone])}>{sub}</div>}
    </div>
  )
}
