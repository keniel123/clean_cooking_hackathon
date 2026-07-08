/**
 * Domain model for the KPLC rural microgrid platform.
 *
 * This file doubles as the schema proposal for the backend team:
 * prefixed string IDs, explicit FKs, ISO-8601 timestamps, units in
 * field names (Kwh, Kw, Pct, Kes).
 */

export type VillageStatus = 'operational' | 'degraded' | 'offline'
/** `disconnected` is a deliberate disconnection (e.g. non-payment); `offline` is a telemetry fault. */
export type MeterStatus = 'online' | 'offline' | 'disconnected'
export type CustomerType = 'household' | 'small_business' | 'institution'
export type TimeRange = '24h' | '7d' | '30d' | '90d'

export interface Village {
  id: string // 'vlg_kalokol'
  name: string
  county: string
  latitude: number
  longitude: number
  commissionedAt: string
  pvCapacityKwp: number
  batteryCapacityKwh: number
  inverterCapacityKw: number
  status: VillageStatus
}

export interface Customer {
  id: string // 'cus_00042'
  villageId: string // FK -> Village.id
  fullName: string
  phoneNumber: string // '+2547...' — M-PESA identity
  customerType: CustomerType
  tariffId: string // FK -> Tariff.id
  connectedAt: string
  accountBalanceKes: number // PAYG credit, never negative
  arrearsKes: number // outstanding owed (0 if current)
  // survey-derived profile metadata (null until surveyed / not applicable)
  householdSize: number | null
  occupation: string | null
  appliancesOwned: string[]
}

export interface Meter {
  id: string // 'mtr_00042'
  customerId: string // FK -> Customer.id (1:1)
  serialNumber: string // 'KPLC-MG-...'
  status: MeterStatus
  installedAt: string
  lastSeenAt: string // last telemetry heartbeat
  latitude: number
  longitude: number
}

export interface Tariff {
  id: string // 'trf_basic'
  name: string
  pricePerKwhKes: number
  dailyServiceChargeKes: number
  loadLimitW: number // appliance/load tier ceiling
}

/** Village-level telemetry point (hourly at source; daily buckets are averages). */
export interface EnergyPoint {
  timestamp: string
  pvGenerationKw: number
  loadKw: number
  batterySocPct: number // 0–100
  batteryPowerKw: number // +charging / -discharging
}

export interface ConsumptionPoint {
  timestamp: string
  consumptionKwh: number
}

export interface RevenuePoint {
  timestamp: string
  amountKes: number
}

export interface Payment {
  id: string // 'pay_...'
  customerId: string // FK
  villageId: string // denormalized FK for village revenue queries
  amountKes: number
  method: 'mpesa'
  mpesaReference: string
  paidAt: string
  kwhPurchased: number
}

export interface SurveyResponse {
  id: string // 'svy_...'
  customerId: string // FK
  campaign: string // 'onboarding' | 'appliance_census_2026' | 'satisfaction_q2'
  channel: 'sms'
  sentAt: string
  respondedAt: string | null // null = no response yet
  answers: Record<string, string> // question key -> raw SMS answer
}

// ---------------------------------------------------------------------------
// View models (aggregates the API returns for dashboard views)
// ---------------------------------------------------------------------------

export interface VillageSummary {
  village: Village
  customerCount: number
  currentSocPct: number
  currentLoadKw: number
  pvTodayKwh: number
  uptimePct30d: number
  revenueMtdKes: number
  customersInArrears: number
}

export interface FleetKpis {
  totalVillages: number
  operationalVillages: number
  totalCustomers: number
  totalPvCapacityKwp: number
  pvTodayKwh: number
  avgSocPct: number
  revenueMtdKes: number
  totalArrearsKes: number
  avgUptimePct30d: number
}

/** Customer list row: customer joined with its meter's current status. */
export interface CustomerRow {
  customer: Customer
  meterStatus: MeterStatus
}

export interface CustomerDetail {
  customer: Customer
  meter: Meter
  tariff: Tariff
  village: Village
  surveyResponses: SurveyResponse[]
}
