import clsx from 'clsx'
import { useSearchParams } from 'react-router'
import type { TimeRange } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'

const RANGES: TimeRange[] = ['24h', '7d', '30d', '90d']

function isTimeRange(value: string | null): value is TimeRange {
  return value !== null && (RANGES as string[]).includes(value)
}

/** Range state lives in the URL (`?range=7d`) so views are shareable. */
export function useTimeRange(defaultRange: TimeRange = '7d'): [TimeRange, (r: TimeRange) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get('range')
  const range = isTimeRange(raw) ? raw : defaultRange
  const setRange = (r: TimeRange) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('range', r)
        return next
      },
      { replace: true },
    )
  }
  return [range, setRange]
}

export function TimeRangeSelector({
  value,
  onChange,
}: {
  value: TimeRange
  onChange: (r: TimeRange) => void
}) {
  const { t } = useI18n()
  return (
    <div className="inline-flex rounded-lg border border-gridline bg-surface p-0.5" role="group">
      {RANGES.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onChange(r)}
          aria-pressed={value === r}
          className={clsx(
            'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
            value === r ? 'bg-ink text-white' : 'text-ink-secondary hover:bg-page',
          )}
        >
          {t.ranges[r]}
        </button>
      ))}
    </div>
  )
}
