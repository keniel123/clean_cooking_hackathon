interface TooltipEntry {
  name?: string | number
  value?: string | number
  color?: string
}

/**
 * Shared tooltip body for all charts. Recharts injects active/label/payload;
 * the chart passes the two formatters.
 */
export function ChartTooltip({
  active,
  label,
  payload,
  labelText,
  valueText,
}: {
  active?: boolean
  label?: unknown
  payload?: TooltipEntry[]
  labelText: (label: string) => string
  valueText: (value: number, name: string) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-gridline bg-surface px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-medium text-ink">{labelText(String(label))}</div>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-1.5 py-0.5">
          <span
            aria-hidden
            className="h-2 w-2 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-ink-secondary">{String(entry.name)}</span>
          <span className="ml-auto pl-3 font-medium tabular-nums text-ink">
            {valueText(Number(entry.value), String(entry.name))}
          </span>
        </div>
      ))}
    </div>
  )
}

/** HTML legend row (ink text + colored mark, per dataviz rules). */
export function ChartLegend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-ink-secondary">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-0.5 w-4 rounded-full"
            style={{ backgroundColor: item.color }}
          />
          {item.label}
        </span>
      ))}
    </div>
  )
}
