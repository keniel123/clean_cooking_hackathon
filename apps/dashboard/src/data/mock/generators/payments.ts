import type { Customer, Payment, Tariff } from '../../../domain/models'
import { chance, float, hashString, int, mulberry32, pickWeighted, type Rng } from '../random'

const HISTORY_DAYS = 90

const AMOUNTS_RETAIL = [
  [50, 35], [100, 30], [200, 20], [500, 10], [1000, 3], [2000, 2],
] as const
const AMOUNTS_INSTITUTION = [
  [500, 40], [1000, 35], [2000, 25],
] as const

// token purchases cluster in the evening, when phones get charged and shops close
const PURCHASE_HOURS = [
  [7, 5], [8, 5], [9, 5], [12, 8], [17, 12], [18, 15], [19, 20], [20, 18], [21, 12],
] as const

const REF_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ123456789'

function mpesaRef(rng: Rng): string {
  let ref = 'S'
  for (let i = 0; i < 9; i++) ref += REF_CHARS[int(rng, 0, REF_CHARS.length - 1)]
  return ref
}

export function buildPaymentsForCustomer(
  customer: Customer,
  tariff: Tariff,
  seed: number,
  now: Date,
  nextId: () => string,
): Payment[] {
  const rng = mulberry32((seed ^ hashString(customer.id)) + 13)
  const nowMs = now.getTime()
  const historyStartMs = Math.max(nowMs - HISTORY_DAYS * 86400e3, new Date(customer.connectedAt).getTime())

  const isInstitution = customer.customerType === 'institution'
  const isBusiness = customer.customerType === 'small_business'
  const amounts = isInstitution ? AMOUNTS_INSTITUTION : AMOUNTS_RETAIL
  const [minGap, maxGap] = isInstitution ? [5, 10] : isBusiness ? [1, 3] : [2, 5]

  const payments: Payment[] = []
  let tMs = historyStartMs + float(rng, 0, maxGap) * 86400e3
  while (tMs < nowMs) {
    // customers sliding into arrears mostly stop topping up in the last 3 weeks
    const inSilentWindow = customer.arrearsKes > 0 && nowMs - tMs < 21 * 86400e3
    if (!inSilentWindow || chance(rng, 0.15)) {
      const day = new Date(tMs)
      day.setHours(pickWeighted(rng, PURCHASE_HOURS), int(rng, 0, 59), int(rng, 0, 59), 0)
      if (day.getTime() < nowMs) {
        const amountKes = pickWeighted(rng, amounts)
        payments.push({
          id: nextId(),
          customerId: customer.id,
          villageId: customer.villageId,
          amountKes,
          method: 'mpesa',
          mpesaReference: mpesaRef(rng),
          paidAt: day.toISOString(),
          kwhPurchased: Math.round((amountKes / tariff.pricePerKwhKes) * 100) / 100,
        })
      }
    }
    tMs += float(rng, minGap, maxGap) * 86400e3
  }
  return payments
}
