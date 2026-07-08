import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
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
import { ChartLegend, ChartTooltip } from './ChartTooltip'

export function EnergyChart({ data, range }: { data: EnergyPoint[]; range: TimeRange }) {
  const { t } = useI18n()
  const hourly = range === '24h' || range === '7d'
  const tick =
    range === '24h' ? formatHourMinute : range === '7d' ? formatWeekdayDay : formatDayMonth
  const tooltipLabel = hourly ? formatDateTime : formatDate
  const pvLabel = hourly ? t.charts.pvGeneration : t.charts.pvGenerationDailyAvg
  const loadLabel = hourly ? t.charts.load : t.charts.loadDailyAvg

  return (
    <div>
      <ChartLegend
        items={[
          { label: pvLabel, color: SERIES.solar },
          { label: loadLabel, color: SERIES.load },
        ]}
      />
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={CHART_INK.grid} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="timestamp"
            tickFormatter={tick}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={{ stroke: CHART_INK.baseline }}
            minTickGap={32}
          />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={44} unit=" kW" />
          <Tooltip
            cursor={{ stroke: CHART_INK.baseline, strokeWidth: 1 }}
            content={
              <ChartTooltip labelText={tooltipLabel} valueText={(v) => `${v.toFixed(1)} kW`} />
            }
          />
          <Area
            type="monotone"
            dataKey="pvGenerationKw"
            name={pvLabel}
            stroke={SERIES.solar}
            strokeWidth={2}
            fill={SERIES.solar}
            fillOpacity={0.1}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }}
          />
          <Line
            type="monotone"
            dataKey="loadKw"
            name={loadLabel}
            stroke={SERIES.load}
            strokeWidth={2}
            strokeLinecap="round"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
