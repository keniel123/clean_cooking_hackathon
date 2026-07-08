import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { RevenuePoint, TimeRange } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import {
  formatDate,
  formatDateTime,
  formatDayMonth,
  formatHourMinute,
  formatKes,
} from '../../lib/format'
import { AXIS_TICK, CHART_INK, compactNumber, SERIES } from './theme'
import { ChartTooltip } from './ChartTooltip'

export function RevenueChart({ data, range }: { data: RevenuePoint[]; range: TimeRange }) {
  const { t } = useI18n()
  const hourly = range === '24h'

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} barCategoryGap="20%">
        <CartesianGrid stroke={CHART_INK.grid} strokeWidth={1} vertical={false} />
        <XAxis
          dataKey="timestamp"
          tickFormatter={hourly ? formatHourMinute : formatDayMonth}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: CHART_INK.baseline }}
          minTickGap={32}
        />
        <YAxis
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={44}
          tickFormatter={compactNumber}
        />
        <Tooltip
          cursor={{ fill: 'rgba(11, 11, 11, 0.04)' }}
          content={
            <ChartTooltip
              labelText={hourly ? formatDateTime : formatDate}
              valueText={(v) => formatKes(v)}
            />
          }
        />
        <Bar
          dataKey="amountKes"
          name={t.charts.collections}
          fill={SERIES.revenue}
          radius={[4, 4, 0, 0]}
          maxBarSize={24}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
