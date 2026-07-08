import { format, startOfDay, startOfHour, startOfMonth, subHours } from 'date-fns'
import type {
  ConsumptionPoint,
  Customer,
  CustomerDetail,
  CustomerRow,
  EnergyPoint,
  FleetKpis,
  Meter,
  Payment,
  RevenuePoint,
  SurveyResponse,
  Tariff,
  TimeRange,
  Village,
  VillageSummary,
} from '../../domain/models'
import type { DataProvider } from '../DataProvider'
import { bucketRevenue, dailyAverageEnergy, rangeStart } from '../series'

/**
 * DataProvider backed by the GridCook Oloika API (apps/api).
 *
 * The API models a single community — the Oloika mini-grid (Magadi ward,
 * Kajiado County) with one month of telemetry (June 2025) — so the mapping to
 * this dashboard's fleet-oriented domain is:
 *
 *   village            <- the `oloika` community (fleet of one)
 *   customer           <- mini-grid account (+ leaderboard name, credit balance)
 *   energy series      <- /grid/hourly telemetry
 *   payment / revenue  <- billing-ledger `top_up` events (cash in)
 *   consumption        <- /accounts/{id}/daily-behavior, sessions for the 24h view
 *   survey profile     <- household / commercial persona records
 *
 * Everything time-based is anchored to the newest telemetry hour rather than
 * the wall clock, so the "last 7 days" views the end of the dataset month.
 * Fields the dataset genuinely lacks are synthesized deterministically and
 * flagged inline (phone numbers, meter serials) or fixed at honest defaults
 * (arrears: the ledger is prepaid-only, so there are none).
 */

const VILLAGE_ID = 'oloika'
const DATASET_START = '2025-06-01T00:00:00'

// Credit model from apps/api/README.md: cooking spends ~10 credits per kWh
// and top-ups are sold at 2 credits per KES.
const CREDITS_PER_KWH = 10
const KES_PER_CREDIT = 0.5

const OLOIKA_TARIFF: Tariff = {
  id: 'trf_oloika_payg',
  name: 'Oloika PAYG credits',
  pricePerKwhKes: CREDITS_PER_KWH * KES_PER_CREDIT,
  dailyServiceChargeKes: 0, // the ledger has no standing-charge events
  loadLimitW: 2400, // 10 A service at 240 V (assumed, not in the dataset)
}

// --------------------------------------------------------------------------
// Raw API rows (only the fields consumed here); see apps/api/README.md
// --------------------------------------------------------------------------

interface ListEnvelope<T> {
  count: number
  results: T[]
}

interface ApiAccount {
  account_id: string
  account_type: 'household' | 'commercial'
  entity_id: string
  meter_status: 'metered' | 'sub_metered'
}

interface ApiLeaderboardRow {
  account_id: string
  display_name: string
}

interface ApiCreditBalance {
  account_id: string
  ending_balance_credits: number
}

interface ApiGridHour {
  timestamp_hour: string
  date: string
  battery_soc_percent: number | null
  battery_power_w: number | null
  pv_dc_power_w: number | null
  pv_ac_power_w: number | null
  fronius_pv_power_w: number | null
  ac_load_w: number | null
  system_alarm_count: number
}

interface ApiBillingRow {
  ledger_id: string
  account_id: string
  credits_delta: number
  cash_kes: number
  created_at: string
}

interface ApiDailyBehavior {
  date: string
  kwh: number
}

interface ApiSession {
  start_at: string
  kwh: number
}

interface ApiHousehold {
  household_id: string
  head_person_id: string
  occupants: number
  meal_count_per_day: number
  income_band_kes_month: string
  primary_equipment: string | null
  secondary_equipment: string | null
  current_fuel_cost_kes_week: number | null
  fuel_collection_minutes_week: number | null
  time_spent_cooking_minutes_day: number | null
  other_grid_uses: string | null
  secondary_microeconomic_activity: string | null
}

interface ApiPerson {
  person_id: string
  primary_activity: string | null
}

interface ApiCommercialProfile {
  business_id: string
  business_type: string
  opening_time: string | null
  closing_time: string | null
  customers_avg_week: number | null
  primary_equipment: string | null
  secondary_equipment: string | null
  fuel_cost_kes_week: number | null
  cooking_hours_day: number | null
  peak_prep_windows: string | null
}

interface PersonaProfile {
  householdSize: number | null
  occupation: string | null
  appliancesOwned: string[]
  answers: Record<string, string>
}

// --------------------------------------------------------------------------

/** FNV-1a; stable per-account seed for synthesized placeholder fields. */
function hashString(s: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

/**
 * The dataset is privacy-preserving (synthetic IDs, no contact info), so the
 * M-PESA identity is a stable placeholder derived from the account id.
 */
function syntheticPhone(accountId: string): string {
  const digits = String(hashString(accountId) % 1e8).padStart(8, '0')
  return `+254 7${digits.slice(0, 2)} ${digits.slice(2, 5)} ${digits.slice(5, 8)}`
}

/** Deterministic coordinate offset (±~400 m) to spread meters around the site. */
function jitter(seed: string): number {
  return ((hashString(seed) % 1000) / 1000 - 0.5) * 0.008
}

function pvWatts(h: ApiGridHour): number {
  // prefer the AC-side reading; fall back to DC / the Fronius-only feed
  return h.pv_ac_power_w ?? h.pv_dc_power_w ?? h.fronius_pv_power_w ?? 0
}

function kw(watts: number): number {
  return Math.round(watts) / 1000
}

function equipmentList(primary: string | null, secondary: string | null): string[] {
  return [primary, secondary].filter((e): e is string => e !== null && e !== '')
}

function toPayment(row: ApiBillingRow): Payment {
  return {
    id: row.ledger_id,
    customerId: row.account_id,
    villageId: VILLAGE_ID,
    amountKes: row.cash_kes,
    method: 'mpesa',
    mpesaReference: row.ledger_id, // the ledger id is the receipt reference
    paidAt: row.created_at,
    kwhPurchased: Math.round((row.credits_delta / CREDITS_PER_KWH) * 10) / 10,
  }
}

export class HttpDataProvider implements DataProvider {
  private readonly baseUrl: string

  private accountsPromise?: Promise<ApiAccount[]>
  private customersPromise?: Promise<CustomerRow[]>
  private gridPromise?: Promise<ApiGridHour[]>
  private topUpsPromise?: Promise<Payment[]>

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
  }

  // ---------------------------------------------------------------- fleet

  async getFleetKpis(): Promise<FleetKpis> {
    const s = await this.summarize()
    return {
      totalVillages: 1,
      operationalVillages: s.village.status === 'operational' ? 1 : 0,
      totalCustomers: s.customerCount,
      totalPvCapacityKwp: s.village.pvCapacityKwp,
      pvTodayKwh: Math.round(s.pvTodayKwh),
      avgSocPct: Math.round(s.currentSocPct),
      revenueMtdKes: s.revenueMtdKes,
      totalArrearsKes: 0,
      avgUptimePct30d: s.uptimePct30d,
    }
  }

  async listVillageSummaries(): Promise<VillageSummary[]> {
    return [await this.summarize()]
  }

  async getFleetRevenueSeries(range: TimeRange): Promise<RevenuePoint[]> {
    const [payments, now] = await Promise.all([this.topUps(), this.anchorNow()])
    return bucketRevenue(payments, range, now)
  }

  // -------------------------------------------------------------- village

  async getVillageSummary(villageId: string): Promise<VillageSummary> {
    this.requireVillage(villageId)
    return this.summarize()
  }

  async getVillageEnergySeries(villageId: string, range: TimeRange): Promise<EnergyPoint[]> {
    this.requireVillage(villageId)
    const [grid, now] = await Promise.all([this.grid(), this.anchorNow()])
    const from = rangeStart(range, now).getTime()
    const points: EnergyPoint[] = grid
      .filter((h) => new Date(h.timestamp_hour).getTime() >= from)
      .map((h) => ({
        timestamp: h.timestamp_hour,
        pvGenerationKw: kw(pvWatts(h)),
        loadKw: kw(h.ac_load_w ?? 0),
        batterySocPct: h.battery_soc_percent ?? 0,
        batteryPowerKw: kw(h.battery_power_w ?? 0), // +charging / -discharging
      }))
    if (range === '24h' || range === '7d') return points
    return dailyAverageEnergy(points)
  }

  async getVillageRevenueSeries(villageId: string, range: TimeRange): Promise<RevenuePoint[]> {
    this.requireVillage(villageId)
    return this.getFleetRevenueSeries(range)
  }

  async listCustomers(villageId: string): Promise<CustomerRow[]> {
    this.requireVillage(villageId)
    return this.customers()
  }

  async listVillagePayments(villageId: string, range: TimeRange): Promise<Payment[]> {
    this.requireVillage(villageId)
    const [payments, now] = await Promise.all([this.topUps(), this.anchorNow()])
    const from = rangeStart(range, now).getTime()
    return payments
      .filter((p) => new Date(p.paidAt).getTime() >= from)
      .sort((a, b) => b.paidAt.localeCompare(a.paidAt))
  }

  // ------------------------------------------------------------- customer

  async getCustomerDetail(customerId: string): Promise<CustomerDetail> {
    const [rows, accounts, village, now] = await Promise.all([
      this.customers(),
      this.accounts(),
      this.village(),
      this.anchorNow(),
    ])
    const row = rows.find((r) => r.customer.id === customerId)
    const account = accounts.find((a) => a.account_id === customerId)
    if (!row || !account) throw new Error(`Customer not found: ${customerId}`)

    const persona =
      account.account_type === 'household'
        ? await this.householdPersona(account.entity_id)
        : await this.commercialPersona(account.entity_id)

    const customer: Customer = {
      ...row.customer,
      householdSize: persona.householdSize,
      occupation: persona.occupation,
      appliancesOwned: persona.appliancesOwned,
    }
    const meter: Meter = {
      id: `mtr_${customerId}`,
      customerId,
      // serials are synthesized: the dataset identifies meters only via
      // the account's metered / sub_metered status
      serialNumber: `OLK-${account.meter_status === 'metered' ? 'MTR' : 'SUB'}-${customerId}`,
      status: 'online',
      installedAt: DATASET_START,
      lastSeenAt: now.toISOString(),
      latitude: village.latitude + jitter(`${customerId}:lat`),
      longitude: village.longitude + jitter(`${customerId}:lng`),
    }
    // The persona record is survey-derived metadata — surface it as the
    // onboarding SMS survey response.
    const surveyResponses: SurveyResponse[] = [
      {
        id: `svy_${customerId}_onboarding`,
        customerId,
        campaign: 'onboarding',
        channel: 'sms',
        sentAt: DATASET_START,
        respondedAt: DATASET_START,
        answers: persona.answers,
      },
    ]
    return { customer, meter, tariff: OLOIKA_TARIFF, village, surveyResponses }
  }

  async getCustomerConsumption(customerId: string, range: TimeRange): Promise<ConsumptionPoint[]> {
    await this.requireCustomer(customerId)
    const now = await this.anchorNow()

    if (range === '24h') {
      // real cooking sessions of the last day, summed into hourly buckets
      const start = startOfHour(subHours(now, 23))
      const dates = [...new Set([format(start, 'yyyy-MM-dd'), format(now, 'yyyy-MM-dd')])]
      const sessions = (
        await Promise.all(
          dates.map((d) =>
            this.listAll<ApiSession>(`/api/v1/sessions?account_id=${customerId}&date=${d}`),
          ),
        )
      ).flat()
      const kwhByHour = new Map<number, number>()
      for (const s of sessions) {
        const t = startOfHour(new Date(s.start_at)).getTime()
        kwhByHour.set(t, (kwhByHour.get(t) ?? 0) + s.kwh)
      }
      return Array.from({ length: 24 }, (_, h) => {
        const ts = new Date(start.getTime() + h * 3600e3)
        return {
          timestamp: ts.toISOString(),
          consumptionKwh: Math.round((kwhByHour.get(ts.getTime()) ?? 0) * 1000) / 1000,
        }
      })
    }

    const behavior = await this.listAll<ApiDailyBehavior>(
      `/api/v1/accounts/${customerId}/daily-behavior`,
    )
    const kwhByDate = new Map(behavior.map((b) => [b.date, b.kwh]))
    const days = range === '7d' ? 7 : range === '30d' ? 30 : 90
    const todayStart = startOfDay(now).getTime()
    const points: ConsumptionPoint[] = []
    for (let d = days - 1; d >= 0; d--) {
      const day = new Date(todayStart - d * 86400e3)
      points.push({
        timestamp: day.toISOString(),
        consumptionKwh: Math.round((kwhByDate.get(format(day, 'yyyy-MM-dd')) ?? 0) * 100) / 100,
      })
    }
    return points
  }

  async listCustomerPayments(customerId: string, range: TimeRange): Promise<Payment[]> {
    await this.requireCustomer(customerId)
    const [payments, now] = await Promise.all([this.topUps(), this.anchorNow()])
    const from = rangeStart(range, now).getTime()
    return payments
      .filter((p) => p.customerId === customerId && new Date(p.paidAt).getTime() >= from)
      .sort((a, b) => b.paidAt.localeCompare(a.paidAt))
  }

  // ------------------------------------------------------------ transport

  private async getJson<T>(path: string): Promise<T> {
    const res = await fetch(this.baseUrl + path, { headers: { Accept: 'application/json' } })
    if (!res.ok) throw new Error(`GET ${path} -> HTTP ${res.status}`)
    return res.json() as Promise<T>
  }

  /** Follow the `{ count, results }` list envelope through every page. */
  private async listAll<T>(path: string): Promise<T[]> {
    const sep = path.includes('?') ? '&' : '?'
    const results: T[] = []
    for (;;) {
      const page = await this.getJson<ListEnvelope<T>>(
        `${path}${sep}limit=500&offset=${results.length}`,
      )
      results.push(...page.results)
      if (results.length >= page.count || page.results.length === 0) return results
    }
  }

  // -------------------------------------------------------------- caches

  private accounts(): Promise<ApiAccount[]> {
    return (this.accountsPromise ??= this.listAll<ApiAccount>('/api/v1/accounts'))
  }

  private grid(): Promise<ApiGridHour[]> {
    return (this.gridPromise ??= this.listAll<ApiGridHour>('/api/v1/grid/hourly'))
  }

  private topUps(): Promise<Payment[]> {
    return (this.topUpsPromise ??= this.listAll<ApiBillingRow>(
      '/api/v1/billing?event_type=top_up',
    ).then((rows) => rows.map(toPayment)))
  }

  private customers(): Promise<CustomerRow[]> {
    return (this.customersPromise ??= this.buildCustomers())
  }

  // ------------------------------------------------------------- mapping

  /** All time windows count back from the newest telemetry hour. */
  private async anchorNow(): Promise<Date> {
    const grid = await this.grid()
    const last = grid.at(-1)
    if (!last) throw new Error('GridCook API returned no grid telemetry')
    return new Date(last.timestamp_hour)
  }

  private requireVillage(villageId: string): void {
    if (villageId !== VILLAGE_ID) throw new Error(`Village not found: ${villageId}`)
  }

  private async requireCustomer(customerId: string): Promise<void> {
    const accounts = await this.accounts()
    if (!accounts.some((a) => a.account_id === customerId)) {
      throw new Error(`Customer not found: ${customerId}`)
    }
  }

  private async village(): Promise<Village> {
    const grid = await this.grid()
    const pvPeakW = grid.reduce((a, h) => Math.max(a, pvWatts(h)), 0)
    const loadPeakW = grid.reduce((a, h) => Math.max(a, h.ac_load_w ?? 0), 0)
    return {
      id: VILLAGE_ID,
      name: 'Oloika',
      county: 'Kajiado',
      latitude: -2.0465, // OSM village node, Magadi ward, Kajiado West
      longitude: 36.2133,
      commissionedAt: DATASET_START,
      // plate ratings aren't in the dataset; report observed June peaks
      pvCapacityKwp: Math.round(pvPeakW / 100) / 10,
      batteryCapacityKwh: 59, // median of overnight discharge-energy / SOC-swing estimates
      inverterCapacityKw: Math.round(loadPeakW / 100) / 10,
      status: 'operational',
    }
  }

  private async summarize(): Promise<VillageSummary> {
    const [village, grid, rows, payments, now] = await Promise.all([
      this.village(),
      this.grid(),
      this.customers(),
      this.topUps(),
      this.anchorNow(),
    ])
    const last = grid.at(-1)
    if (!last) throw new Error('GridCook API returned no grid telemetry')
    const pvTodayKwh = grid
      .filter((h) => h.date === last.date)
      .reduce((a, h) => a + pvWatts(h) / 1000, 0) // hourly points → kW·1h = kWh
    const monthStart = startOfMonth(now).getTime()
    const revenueMtdKes = payments
      .filter((p) => new Date(p.paidAt).getTime() >= monthStart)
      .reduce((a, p) => a + p.amountKes, 0)
    // the feed emits ~4 routine alarms per hour; an alarm spike marks a degraded hour
    const healthyHours = grid.filter((h) => h.system_alarm_count < 10).length
    return {
      village,
      customerCount: rows.length,
      currentSocPct: last.battery_soc_percent ?? 0,
      currentLoadKw: kw(last.ac_load_w ?? 0),
      pvTodayKwh: Math.round(pvTodayKwh * 10) / 10,
      uptimePct30d: Math.round((healthyHours / grid.length) * 1000) / 10,
      revenueMtdKes,
      customersInArrears: 0, // prepaid credits never go negative — no arrears
    }
  }

  private async buildCustomers(): Promise<CustomerRow[]> {
    const [accounts, leaderboard, balances] = await Promise.all([
      this.accounts(),
      this.listAll<ApiLeaderboardRow>('/api/v1/leaderboard'),
      this.listAll<ApiCreditBalance>('/api/v1/credit-balances'),
    ])
    const nameById = new Map(leaderboard.map((r) => [r.account_id, r.display_name]))
    const creditsById = new Map(balances.map((b) => [b.account_id, b.ending_balance_credits]))
    return accounts.map((a) => ({
      customer: {
        id: a.account_id,
        villageId: VILLAGE_ID,
        fullName:
          nameById.get(a.account_id) ??
          (a.account_type === 'commercial'
            ? `Business ${a.account_id}`
            : `Household ${a.account_id}`),
        phoneNumber: syntheticPhone(a.account_id),
        customerType: a.account_type === 'commercial' ? 'small_business' : 'household',
        tariffId: OLOIKA_TARIFF.id,
        connectedAt: DATASET_START,
        accountBalanceKes: Math.round((creditsById.get(a.account_id) ?? 0) * KES_PER_CREDIT),
        arrearsKes: 0,
        householdSize: null, // persona fields load with the detail view
        occupation: null,
        appliancesOwned: [],
      },
      meterStatus: 'online' as const,
    }))
  }

  private async householdPersona(householdId: string): Promise<PersonaProfile> {
    const [hh, people] = await Promise.all([
      this.getJson<ApiHousehold>(`/api/v1/households/${householdId}`),
      this.listAll<ApiPerson>(`/api/v1/households/${householdId}/people`),
    ])
    const head = people.find((p) => p.person_id === hh.head_person_id) ?? people[0]
    const occupation = head?.primary_activity ?? hh.secondary_microeconomic_activity
    const appliances = equipmentList(hh.primary_equipment, hh.secondary_equipment)
    const answers: Record<string, string> = {
      household_size: String(hh.occupants),
      meals_per_day: String(hh.meal_count_per_day),
      income_band: hh.income_band_kes_month.replaceAll('_', ' '),
    }
    if (occupation) answers.occupation = occupation
    if (appliances.length > 0) answers.appliances = appliances.join(', ')
    if (hh.current_fuel_cost_kes_week !== null)
      answers.weekly_fuel_spend = `KES ${hh.current_fuel_cost_kes_week}`
    if (hh.fuel_collection_minutes_week !== null)
      answers.fuel_collection_per_week = `${hh.fuel_collection_minutes_week} min`
    if (hh.time_spent_cooking_minutes_day !== null)
      answers.cooking_time_per_day = `${hh.time_spent_cooking_minutes_day} min`
    if (hh.other_grid_uses) answers.other_grid_uses = hh.other_grid_uses.replaceAll(';', ', ')
    return { householdSize: hh.occupants, occupation, appliancesOwned: appliances, answers }
  }

  private async commercialPersona(businessId: string): Promise<PersonaProfile> {
    const biz = await this.getJson<ApiCommercialProfile>(
      `/api/v1/commercial-profiles/${businessId}`,
    )
    const appliances = equipmentList(biz.primary_equipment, biz.secondary_equipment)
    const answers: Record<string, string> = { business_type: biz.business_type }
    if (biz.opening_time && biz.closing_time)
      answers.opening_hours = `${biz.opening_time}–${biz.closing_time}`
    if (biz.customers_avg_week !== null)
      answers.customers_per_week = String(biz.customers_avg_week)
    if (appliances.length > 0) answers.appliances = appliances.join(', ')
    if (biz.fuel_cost_kes_week !== null) answers.weekly_fuel_spend = `KES ${biz.fuel_cost_kes_week}`
    if (biz.cooking_hours_day !== null)
      answers.cooking_hours_per_day = String(biz.cooking_hours_day)
    if (biz.peak_prep_windows) answers.peak_prep_windows = biz.peak_prep_windows.replaceAll(';', ', ')
    return {
      householdSize: null,
      occupation: biz.business_type,
      appliancesOwned: appliances,
      answers,
    }
  }
}
