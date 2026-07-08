import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { EnergyPoint, TimeRange } from '../../domain/models'
import { useI18n } from '../../i18n/I18nContext'
import {
  formatDate,
  formatDateTime,
  formatDayMonth,
  formatHourMinute,
  formatWeekdayDay,
} from '../../lib/format'
import { AXIS_TICK, CHART_INK, SERIES } from './theme'
import { ChartTooltip } from './ChartTooltip'

export function SocChart({ data, range }: { data: EnergyPoint[]; range: TimeRange }) {
  const { t } = useI18n()
  const hourly = range === '24h' || range === '7d'
  const tick =
    range === '24h' ? formatHourMinute : range === '7d' ? formatWeekdayDay : formatDayMonth

  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={CHART_INK.grid} strokeWidth={1} vertical={false} />
        <XAxis
          dataKey="timestamp"
          tickFormatter={tick}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: CHART_INK.baseline }}
          minTickGap={32}
        />
        <YAxis domain={[0, 100]} tick={AXIS_TICK} tickLine={false} axisLine={false} width={40} unit="%" />
        <Tooltip
          cursor={{ stroke: CHART_INK.baseline, strokeWidth: 1 }}
          content={
            <ChartTooltip
              labelText={hourly ? formatDateTime : formatDate}
              valueText={(v) => `${v.toFixed(0)}%`}
            />
          }
        />
        {/* 20% floor: the battery's protection cutoff */}
        <ReferenceLine y={20} stroke={CHART_INK.critical} strokeOpacity={0.35} strokeWidth={1} />
        <Area
          type="monotone"
          dataKey="batterySocPct"
          name={t.charts.batterySoc}
          stroke={SERIES.battery}
          strokeWidth={2}
          fill={SERIES.battery}
          fillOpacity={0.1}
          dot={false}
          activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
