import type {
  ConsumptionPoint,
  CustomerDetail,
  CustomerRow,
  EnergyPoint,
  FleetKpis,
  Payment,
  RevenuePoint,
  TimeRange,
  VillageSummary,
} from '../domain/models'

/**
 * The swap boundary between the UI and the data source.
 *
 * Every method maps 1:1 to a future REST endpoint on the real backend;
 * `MockDataProvider` is the in-memory stand-in. Swapping in an
 * `HttpDataProvider` must require no UI changes.
 */
export interface DataProvider {
  // fleet / overview
  getFleetKpis(): Promise<FleetKpis>
  listVillageSummaries(): Promise<VillageSummary[]>
  getFleetRevenueSeries(range: TimeRange): Promise<RevenuePoint[]>

  // village
  getVillageSummary(villageId: string): Promise<VillageSummary>
  getVillageEnergySeries(villageId: string, range: TimeRange): Promise<EnergyPoint[]>
  getVillageRevenueSeries(villageId: string, range: TimeRange): Promise<RevenuePoint[]>
  listCustomers(villageId: string): Promise<CustomerRow[]>
  listVillagePayments(villageId: string, range: TimeRange): Promise<Payment[]>

  // customer
  getCustomerDetail(customerId: string): Promise<CustomerDetail>
  getCustomerConsumption(customerId: string, range: TimeRange): Promise<ConsumptionPoint[]>
  listCustomerPayments(customerId: string, range: TimeRange): Promise<Payment[]>
}
