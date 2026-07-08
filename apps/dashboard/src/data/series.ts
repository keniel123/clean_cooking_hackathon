import { startOfDay, subDays, subHours } from 'date-fns'
import type { EnergyPoint, Payment, RevenuePoint, TimeRange } from '../domain/models'

/** Start of a time range counting back from `now`. */
export function rangeStart(range: TimeRange, now: Date): Date {
  switch (range) {
    case '24h':
      return subHours(now, 24)
    case '7d':
      return subDays(now, 7)
    case '30d':
      return subDays(now, 30)
    case '90d':
      return subDays(now, 90)
  }
}

/** Collapse hourly energy points into one average point per day. */
export function dailyAverageEnergy(points: EnergyPoint[]): EnergyPoint[] {
  const byDay = new Map<string, EnergyPoint[]>()
  for (const p of points) {
    const key = startOfDay(new Date(p.timestamp)).toISOString()
    const bucket = byDay.get(key)
    if (bucket) bucket.push(p)
    else byDay.set(key, [p])
  }
  return [...byDay.entries()].map(([timestamp, pts]) => {
    const avg = (get: (p: EnergyPoint) => number) =>
      Math.round((pts.reduce((a, p) => a + get(p), 0) / pts.length) * 100) / 100
    return {
      timestamp,
      pvGenerationKw: avg((p) => p.pvGenerationKw),
      loadKw: avg((p) => p.loadKw),
      batterySocPct: avg((p) => p.batterySocPct),
      batteryPowerKw: avg((p) => p.batteryPowerKw),
    }
  })
}

/** Sum payments into hourly (24h) or daily buckets, ending at `now`. */
export function bucketRevenue(payments: Payment[], range: TimeRange, now: Date): RevenuePoint[] {
  const from = rangeStart(range, now)
  const hourly = range === '24h'
  const stepMs = hourly ? 3600e3 : 86400e3
  const startMs = hourly ? from.getTime() : startOfDay(from).getTime()
  const buckets = hourly ? 24 : range === '7d' ? 8 : range === '30d' ? 31 : 91

  const series: RevenuePoint[] = []
  for (let i = 0; i < buckets; i++) {
    const bucketStart = startMs + i * stepMs
    if (bucketStart > now.getTime()) break
    series.push({ timestamp: new Date(bucketStart).toISOString(), amountKes: 0 })
  }
  for (const p of payments) {
    const t = new Date(p.paidAt).getTime()
    if (t < startMs) continue
    const idx = Math.floor((t - startMs) / stepMs)
    const bucket = series[idx]
    if (bucket) bucket.amountKes += p.amountKes
  }
  return series
}
