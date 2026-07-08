import { startOfDay, startOfHour, startOfMonth, subHours } from 'date-fns'
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
  VillageSummary,
} from '../../domain/models'
import type { DataProvider } from '../DataProvider'
import { bucketRevenue, dailyAverageEnergy, rangeStart } from '../series'
import { buildCustomersForVillage } from './generators/customers'
import { buildVillageEnergy, type VillageEnergy } from './generators/energy'
import { buildPaymentsForCustomer } from './generators/payments'
import { buildSurveysForCustomer } from './generators/surveys'
import { float, hashString, mulberry32 } from './random'
import { TARIFFS, VILLAGES } from './villages.seed'

// hourly load shape reused to spread a customer's daily kWh across the day
const HOURLY_SHAPE = [
  0.28, 0.24, 0.22, 0.22, 0.24, 0.34, 0.5, 0.55, 0.42, 0.35, 0.32, 0.33,
  0.35, 0.34, 0.32, 0.34, 0.45, 0.65, 0.94, 1.0, 0.96, 0.75, 0.5, 0.35,
]
const SHAPE_SUM = HOURLY_SHAPE.reduce((a, b) => a + b, 0)

const DAILY_KWH_BY_TARIFF: Record<string, number> = {
  trf_basic: 0.35,
  trf_standard: 1.1,
  trf_business: 3.2,
  trf_institution: 5.5,
}

/**
 * Deterministic in-memory implementation of DataProvider.
 * Same seed → same data on every refresh (time is anchored to the start of
 * the current hour). Artificial 50–250ms latency keeps loading states honest.
 */
export class MockDataProvider implements DataProvider {
  private readonly now: Date
  private readonly seed: number
  private readonly tariffs = new Map<string, Tariff>()
  private readonly customers: Customer[] = []
  private readonly metersByCustomer = new Map<string, Meter>()
  private readonly customersByVillage = new Map<string, Customer[]>()
  private readonly paymentsByVillage = new Map<string, Payment[]>()
  private readonly paymentsByCustomer = new Map<string, Payment[]>()
  private readonly surveysByCustomer = new Map<string, SurveyResponse[]>()
  private readonly energyCache = new Map<string, VillageEnergy>()
  private readonly consumptionCache = new Map<string, number[]>() // daily kWh, oldest first

  constructor(seed = 42) {
    this.seed = seed
    this.now = startOfHour(new Date())

    for (const t of TARIFFS) this.tariffs.set(t.id, t)

    let paymentCounter = 0
    let surveyCounter = 0
    const nextPaymentId = () => `pay_${String(++paymentCounter).padStart(6, '0')}`
    const nextSurveyId = () => `svy_${String(++surveyCounter).padStart(6, '0')}`

    let customerIndex = 1
    for (const village of VILLAGES) {
      const withMeters = buildCustomersForVillage(village, seed, this.now, customerIndex)
      customerIndex += withMeters.length
      const villageCustomers: Customer[] = []
      const villagePayments: Payment[] = []
      for (const { customer, meter } of withMeters) {
        this.customers.push(customer)
        villageCustomers.push(customer)
        this.metersByCustomer.set(customer.id, meter)

        const tariff = this.tariffs.get(customer.tariffId)!
        const payments = buildPaymentsForCustomer(customer, tariff, seed, this.now, nextPaymentId)
        this.paymentsByCustomer.set(customer.id, payments)
        villagePayments.push(...payments)

        this.surveysByCustomer.set(
          customer.id,
          buildSurveysForCustomer(customer, seed, this.now, nextSurveyId),
        )
      }
      villagePayments.sort((a, b) => a.paidAt.localeCompare(b.paidAt))
      this.customersByVillage.set(village.id, villageCustomers)
      this.paymentsByVillage.set(village.id, villagePayments)
    }
  }

  // ---------------------------------------------------------------- fleet

  async getFleetKpis(): Promise<FleetKpis> {
    await this.latency()
    const summaries = VILLAGES.map((v) => this.summarize(v.id))
    return {
      totalVillages: summaries.length,
      operationalVillages: summaries.filter((s) => s.village.status === 'operational').length,
      totalCustomers: summaries.reduce((a, s) => a + s.customerCount, 0),
      totalPvCapacityKwp: summaries.reduce((a, s) => a + s.village.pvCapacityKwp, 0),
      pvTodayKwh: Math.round(summaries.reduce((a, s) => a + s.pvTodayKwh, 0)),
      avgSocPct: Math.round(summaries.reduce((a, s) => a + s.currentSocPct, 0) / summaries.length),
      revenueMtdKes: summaries.reduce((a, s) => a + s.revenueMtdKes, 0),
      totalArrearsKes: this.customers.reduce((a, c) => a + c.arrearsKes, 0),
      avgUptimePct30d:
        Math.round((summaries.reduce((a, s) => a + s.uptimePct30d, 0) / summaries.length) * 10) / 10,
    }
  }

  async listVillageSummaries(): Promise<VillageSummary[]> {
    await this.latency()
    return VILLAGES.map((v) => this.summarize(v.id))
  }

  async getFleetRevenueSeries(range: TimeRange): Promise<RevenuePoint[]> {
    await this.latency()
    const all = [...this.paymentsByVillage.values()].flat()
    return bucketRevenue(all, range, this.now)
  }

  // -------------------------------------------------------------- village

  async getVillageSummary(villageId: string): Promise<VillageSummary> {
    await this.latency()
    this.requireVillage(villageId)
    return this.summarize(villageId)
  }

  async getVillageEnergySeries(villageId: string, range: TimeRange): Promise<EnergyPoint[]> {
    await this.latency()
    this.requireVillage(villageId)
    const { points } = this.energy(villageId)
    const from = rangeStart(range, this.now).getTime()
    const inRange = points.filter((p) => new Date(p.timestamp).getTime() >= from)
    if (range === '24h' || range === '7d') return inRange
    return dailyAverageEnergy(inRange)
  }

  async getVillageRevenueSeries(villageId: string, range: TimeRange): Promise<RevenuePoint[]> {
    await this.latency()
    this.requireVillage(villageId)
    return bucketRevenue(this.paymentsByVillage.get(villageId) ?? [], range, this.now)
  }

  async listCustomers(villageId: string): Promise<CustomerRow[]> {
    await this.latency()
    this.requireVillage(villageId)
    return (this.customersByVillage.get(villageId) ?? []).map((customer) => ({
      customer,
      meterStatus: this.metersByCustomer.get(customer.id)!.status,
    }))
  }

  async listVillagePayments(villageId: string, range: TimeRange): Promise<Payment[]> {
    await this.latency()
    this.requireVillage(villageId)
    const from = rangeStart(range, this.now).getTime()
    return (this.paymentsByVillage.get(villageId) ?? [])
      .filter((p) => new Date(p.paidAt).getTime() >= from)
      .sort((a, b) => b.paidAt.localeCompare(a.paidAt))
  }

  // ------------------------------------------------------------- customer

  async getCustomerDetail(customerId: string): Promise<CustomerDetail> {
    await this.latency()
    const customer = this.customers.find((c) => c.id === customerId)
    if (!customer) throw new Error(`Customer not found: ${customerId}`)
    const meter = this.metersByCustomer.get(customerId)!
    const tariff = this.tariffs.get(customer.tariffId)!
    const village = VILLAGES.find((v) => v.id === customer.villageId)!
    const surveyResponses = [...(this.surveysByCustomer.get(customerId) ?? [])].sort((a, b) =>
      b.sentAt.localeCompare(a.sentAt),
    )
    return { customer, meter, tariff, village, surveyResponses }
  }

  async getCustomerConsumption(customerId: string, range: TimeRange): Promise<ConsumptionPoint[]> {
    await this.latency()
    const customer = this.customers.find((c) => c.id === customerId)
    if (!customer) throw new Error(`Customer not found: ${customerId}`)
    const daily = this.consumption(customer)
    const dayMs = 86400e3
    const todayStart = startOfDay(this.now).getTime()

    if (range === '24h') {
      // spread the two most recent daily totals across their hours
      const points: ConsumptionPoint[] = []
      const start = subHours(this.now, 24)
      for (let h = 0; h < 24; h++) {
        const ts = new Date(start.getTime() + h * 3600e3)
        const dayIndex = daily.length - 1 - Math.floor((todayStart - startOfDay(ts).getTime()) / dayMs)
        const dayTotal = daily[dayIndex] ?? 0
        points.push({
          timestamp: ts.toISOString(),
          consumptionKwh:
            Math.round(((dayTotal * (HOURLY_SHAPE[ts.getHours()] ?? 0.4)) / SHAPE_SUM) * 1000) / 1000,
        })
      }
      return points
    }

    const days = range === '7d' ? 7 : range === '30d' ? 30 : 90
    const points: ConsumptionPoint[] = []
    for (let d = days - 1; d >= 0; d--) {
      const dayIndex = daily.length - 1 - d
      points.push({
        timestamp: new Date(todayStart - d * dayMs).toISOString(),
        consumptionKwh: Math.round((daily[dayIndex] ?? 0) * 100) / 100,
      })
    }
    return points
  }

  async listCustomerPayments(customerId: string, range: TimeRange): Promise<Payment[]> {
    await this.latency()
    const from = rangeStart(range, this.now).getTime()
    return (this.paymentsByCustomer.get(customerId) ?? [])
      .filter((p) => new Date(p.paidAt).getTime() >= from)
      .sort((a, b) => b.paidAt.localeCompare(a.paidAt))
  }

  // -------------------------------------------------------------- helpers

  private latency(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 50 + Math.random() * 200))
  }

  private requireVillage(villageId: string): void {
    if (!VILLAGES.some((v) => v.id === villageId)) {
      throw new Error(`Village not found: ${villageId}`)
    }
  }

  private energy(villageId: string): VillageEnergy {
    let cached = this.energyCache.get(villageId)
    if (!cached) {
      const village = VILLAGES.find((v) => v.id === villageId)!
      const customerCount = this.customersByVillage.get(villageId)?.length ?? 0
      cached = buildVillageEnergy(village, customerCount, this.seed, this.now)
      this.energyCache.set(villageId, cached)
    }
    return cached
  }

  private consumption(customer: Customer): number[] {
    let cached = this.consumptionCache.get(customer.id)
    if (!cached) {
      const rng = mulberry32((this.seed ^ hashString(customer.id)) + 53)
      const base = DAILY_KWH_BY_TARIFF[customer.tariffId] ?? 1
      const connectedMs = new Date(customer.connectedAt).getTime()
      const todayStart = startOfDay(this.now).getTime()
      cached = []
      for (let d = 90; d >= 0; d--) {
        const dayStart = todayStart - d * 86400e3
        if (dayStart < connectedMs) {
          cached.push(0)
          continue
        }
        const weekend = [0, 6].includes(new Date(dayStart).getDay())
        const weekendFactor =
          customer.customerType === 'household' ? (weekend ? 1.1 : 1) : weekend ? 0.85 : 1
        // deliberate disconnection: no consumption in the recent window
        const meter = this.metersByCustomer.get(customer.id)
        const disconnectedRecently = meter?.status === 'disconnected' && d < 14
        cached.push(disconnectedRecently ? 0 : base * weekendFactor * float(rng, 0.7, 1.3))
      }
      this.consumptionCache.set(customer.id, cached)
    }
    return cached
  }

  private summarize(villageId: string): VillageSummary {
    const village = VILLAGES.find((v) => v.id === villageId)!
    const customers = this.customersByVillage.get(villageId) ?? []
    const { points, uptimePct30d } = this.energy(villageId)
    const last = points[points.length - 1]!
    const todayStart = startOfDay(this.now).getTime()
    const pvTodayKwh = points
      .filter((p) => new Date(p.timestamp).getTime() >= todayStart)
      .reduce((a, p) => a + p.pvGenerationKw, 0) // hourly points → kW·1h = kWh
    const monthStart = startOfMonth(this.now).getTime()
    const revenueMtdKes = (this.paymentsByVillage.get(villageId) ?? [])
      .filter((p) => new Date(p.paidAt).getTime() >= monthStart)
      .reduce((a, p) => a + p.amountKes, 0)
    return {
      village,
      customerCount: customers.length,
      currentSocPct: last.batterySocPct,
      currentLoadKw: last.loadKw,
      pvTodayKwh: Math.round(pvTodayKwh * 10) / 10,
      uptimePct30d,
      revenueMtdKes,
      customersInArrears: customers.filter((c) => c.arrearsKes > 0).length,
    }
  }

}
