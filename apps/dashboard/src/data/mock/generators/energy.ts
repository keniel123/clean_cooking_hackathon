import type { EnergyPoint, Village } from '../../../domain/models'
import { chance, clamp, float, hashString, int, mulberry32, type Rng } from '../random'

export const HISTORY_DAYS = 90
const HOURS = HISTORY_DAYS * 24

// aggregate load shape by hour of day, normalized to 1.0 at the evening peak;
// small morning bump, business daytime plateau, strong 19–22h peak
const LOAD_SHAPE = [
  0.28, 0.24, 0.22, 0.22, 0.24, 0.34, 0.5, 0.55, 0.42, 0.35, 0.32, 0.33,
  0.35, 0.34, 0.32, 0.34, 0.45, 0.65, 0.94, 1.0, 0.96, 0.75, 0.5, 0.35,
]

const SUNRISE_H = 6.5
const SUNSET_H = 18.75

export interface VillageEnergy {
  points: EnergyPoint[]
  uptimePct30d: number
}

interface Outage {
  start: number // hour index
  end: number
}

function buildOutages(rng: Rng, village: Village): Outage[] {
  const outages: Outage[] = []
  const perMonth = village.status === 'degraded' ? [3, 6] : [1, 3]
  for (let month = 0; month < 3; month++) {
    const n = int(rng, perMonth[0]!, perMonth[1]!)
    for (let i = 0; i < n; i++) {
      const start = month * 30 * 24 + int(rng, 0, 30 * 24 - 20)
      const duration = village.status === 'degraded' ? int(rng, 4, 18) : int(rng, 2, 8)
      outages.push({ start, end: Math.min(start + duration, HOURS) })
    }
  }
  // an offline site's defining outage: telemetry dark for the last ~3 days
  if (village.status === 'offline') {
    outages.push({ start: HOURS - 72, end: HOURS })
  }
  return outages
}

/** Deterministic 90 days of hourly telemetry for one village. */
export function buildVillageEnergy(
  village: Village,
  customerCount: number,
  seed: number,
  now: Date,
): VillageEnergy {
  const rng = mulberry32((seed ^ hashString(village.id)) + 7)
  const startMs = now.getTime() - HOURS * 3600e3

  // per-day sky clearness, weighted toward clear equatorial days
  const clearness: number[] = []
  for (let d = 0; d <= HISTORY_DAYS; d++) clearness.push(1 - 0.45 * rng() ** 2)

  const outages = buildOutages(rng, village)
  const inOutage = (h: number) => outages.some((o) => h >= o.start && h < o.end)

  const peakLoadKw = customerCount * 0.12 + village.pvCapacityKwp * 0.1

  const points: EnergyPoint[] = []
  let soc = 55
  for (let h = 0; h < HOURS; h++) {
    const ts = new Date(startMs + h * 3600e3)
    const hourOfDay = ts.getHours() + ts.getMinutes() / 60
    const day = Math.floor(h / 24)

    let pv = 0
    if (hourOfDay >= SUNRISE_H && hourOfDay <= SUNSET_H) {
      const df = (hourOfDay - SUNRISE_H) / (SUNSET_H - SUNRISE_H)
      const cloudDip = chance(rng, 0.15) ? float(rng, 0.5, 0.8) : float(rng, 0.92, 1)
      pv = village.pvCapacityKwp * Math.sin(Math.PI * df) ** 1.3 * (clearness[day] ?? 0.8) * cloudDip
    }
    let load = peakLoadKw * (LOAD_SHAPE[ts.getHours()] ?? 0.4) * float(rng, 0.9, 1.1)

    let batteryPowerKw = 0
    if (inOutage(h)) {
      pv = 0
      load = 0
    } else {
      const prevSoc = soc
      soc = clamp(soc + ((pv - load) * 1 * 100) / village.batteryCapacityKwh, 20, 100)
      batteryPowerKw = ((soc - prevSoc) / 100) * village.batteryCapacityKwh
    }

    points.push({
      timestamp: ts.toISOString(),
      pvGenerationKw: Math.round(pv * 100) / 100,
      loadKw: Math.round(load * 100) / 100,
      batterySocPct: Math.round(soc * 10) / 10,
      batteryPowerKw: Math.round(batteryPowerKw * 100) / 100,
    })
  }

  const last30 = HOURS - 30 * 24
  let outageHours = 0
  for (let h = last30; h < HOURS; h++) if (inOutage(h)) outageHours++
  const uptimePct30d = Math.round((1 - outageHours / (30 * 24)) * 1000) / 10

  return { points, uptimePct30d }
}
