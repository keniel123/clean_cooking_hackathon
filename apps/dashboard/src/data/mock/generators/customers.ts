import type { Customer, CustomerType, Meter, Village } from '../../../domain/models'
import {
  chance,
  clamp,
  float,
  hashString,
  int,
  mulberry32,
  normal,
  pick,
  pickWeighted,
  type Rng,
} from '../random'

const FIRST_NAMES = [
  'John', 'Peter', 'David', 'Samuel', 'Joseph', 'James', 'Daniel', 'Paul',
  'Stephen', 'Francis', 'Michael', 'George', 'Mary', 'Grace', 'Jane', 'Esther',
  'Faith', 'Mercy', 'Sarah', 'Agnes', 'Ruth', 'Catherine', 'Beatrice', 'Joyce',
  'Elizabeth', 'Margaret', 'Simon', 'Philip', 'Anne', 'Lucy',
]

const SURNAMES_BY_COUNTY: Record<string, string[]> = {
  Turkana: ['Ekai', 'Ekiru', 'Lokwang', 'Emoru', 'Lomuria', 'Akai', 'Ewoi', 'Epat', 'Ikeny', 'Nakali', 'Lokol', 'Apalia'],
  Marsabit: ['Guyo', 'Galgalo', 'Adan', 'Wario', 'Halake', 'Boru', 'Dida', 'Jarso', 'Duba', 'Sora'],
  Samburu: ['Lekupe', 'Leshan', 'Lenairoshi', 'Lekimain', 'Letoluai', 'Lengees', 'Lemarkat', 'Leadismo'],
  Kitui: ['Mutua', 'Kioko', 'Musyoka', 'Mwangangi', 'Nzioka', 'Kilonzo', 'Muthoka', 'Wambua', 'Mwende', 'Kimanzi'],
  'Homa Bay': ['Otieno', 'Odhiambo', 'Ochieng', 'Owino', 'Okoth', 'Onyango', 'Awuor', 'Adoyo', 'Omondi', 'Ouma'],
}

const OCCUPATIONS_BY_COUNTY: Record<string, readonly (readonly [string, number])[]> = {
  Turkana: [['pastoralist', 25], ['fisherman', 20], ['shopkeeper', 15], ['charcoal seller', 10], ['teacher', 8], ['tailor', 8], ['boda boda rider', 10], ['livestock trader', 4]],
  Marsabit: [['pastoralist', 30], ['livestock trader', 15], ['shopkeeper', 15], ['teacher', 8], ['tailor', 8], ['boda boda rider', 12], ['charcoal seller', 12]],
  Samburu: [['pastoralist', 35], ['livestock trader', 15], ['shopkeeper', 15], ['teacher', 8], ['boda boda rider', 12], ['beadwork seller', 15]],
  Kitui: [['farmer', 35], ['shopkeeper', 15], ['teacher', 10], ['tailor', 10], ['boda boda rider', 15], ['charcoal trader', 10], ['brick maker', 5]],
  'Homa Bay': [['fisherman', 30], ['fish trader', 15], ['farmer', 20], ['shopkeeper', 12], ['boda boda rider', 12], ['teacher', 6], ['tailor', 5]],
}

const INSTITUTION_KINDS = [
  'Primary School', 'Secondary School', 'Health Dispensary', 'Catholic Mission',
  'ACK Church', 'Chief’s Camp', 'Community Hall',
]

const BUSINESS_APPLIANCES = [
  'refrigerator', 'hair clippers', 'sound system', 'sewing machine',
  'welding machine', 'maize mill', 'water pump', 'photocopier',
]

export interface CustomerWithMeter {
  customer: Customer
  meter: Meter
}

function customerType(rng: Rng): CustomerType {
  return pickWeighted(rng, [
    ['household', 72],
    ['small_business', 23],
    ['institution', 5],
  ] as const)
}

function tariffFor(rng: Rng, type: CustomerType): string {
  if (type === 'institution') return 'trf_institution'
  if (type === 'small_business') return 'trf_business'
  return chance(rng, 0.6) ? 'trf_basic' : 'trf_standard'
}

function appliances(rng: Rng, type: CustomerType, tariffId: string): string[] {
  const owned = ['LED lights', 'phone charger']
  if (chance(rng, 0.6)) owned.push('radio')
  if (tariffId !== 'trf_basic' && chance(rng, 0.45)) owned.push('TV')
  if (type === 'household' && chance(rng, 0.08)) owned.push('refrigerator')
  if (type === 'small_business') {
    const extras = int(rng, 1, 3)
    for (let i = 0; i < extras; i++) {
      const a = pick(rng, BUSINESS_APPLIANCES)
      if (!owned.includes(a)) owned.push(a)
    }
  }
  if (type === 'institution') {
    owned.push('refrigerator')
    if (chance(rng, 0.5)) owned.push('computer')
    if (chance(rng, 0.4)) owned.push('water pump')
  }
  return owned
}

function isoBetween(rng: Rng, fromMs: number, toMs: number): string {
  return new Date(fromMs + rng() * Math.max(toMs - fromMs, 1)).toISOString()
}

export function buildCustomersForVillage(
  village: Village,
  seed: number,
  now: Date,
  startIndex: number,
): CustomerWithMeter[] {
  const rng = mulberry32(seed ^ hashString(village.id))
  const count = Math.round(clamp(village.pvCapacityKwp * 2.4 * float(rng, 0.85, 1.15), 30, 150))
  const surnames = SURNAMES_BY_COUNTY[village.county] ?? SURNAMES_BY_COUNTY['Kitui']!
  const occupations = OCCUPATIONS_BY_COUNTY[village.county] ?? OCCUPATIONS_BY_COUNTY['Kitui']!

  const commissionedMs = new Date(village.commissionedAt).getTime()
  const nowMs = now.getTime()
  const out: CustomerWithMeter[] = []
  const usedInstitutions = new Set<string>()

  for (let i = 0; i < count; i++) {
    const n = startIndex + i
    const id = `cus_${String(n).padStart(5, '0')}`
    const type = customerType(rng)
    const tariffId = tariffFor(rng, type)

    let fullName: string
    if (type === 'institution') {
      let kind = pick(rng, INSTITUTION_KINDS)
      while (usedInstitutions.has(kind) && usedInstitutions.size < INSTITUTION_KINDS.length) {
        kind = pick(rng, INSTITUTION_KINDS)
      }
      usedInstitutions.add(kind)
      fullName = `${village.name} ${kind}`
    } else {
      fullName = `${pick(rng, FIRST_NAMES)} ${pick(rng, surnames)}`
    }

    const connectedAt = isoBetween(
      rng,
      commissionedMs + 7 * 86400e3,
      Math.min(nowMs - 14 * 86400e3, commissionedMs + 400 * 86400e3),
    )

    const inArrears = type !== 'institution' && chance(rng, 0.12)
    const arrearsKes = inArrears ? int(rng, 150, 3000) : 0
    const accountBalanceKes = inArrears
      ? int(rng, 0, 30)
      : Math.round(Math.exp(float(rng, 2.5, 6.5))) // ~12–650 KES, skewed low

    // meter status: whole-village telemetry outage dominates; then
    // deliberate disconnection for deep arrears; then random comms faults
    const villageOffline = village.status === 'offline'
    const disconnected = inArrears && arrearsKes > 1500 && chance(rng, 0.6)
    const meterOffline = villageOffline || (!disconnected && chance(rng, 0.05))
    const lastSeenAt = villageOffline
      ? new Date(nowMs - float(rng, 2.8, 3.2) * 86400e3).toISOString()
      : meterOffline
        ? new Date(nowMs - float(rng, 1, 10) * 86400e3).toISOString()
        : new Date(nowMs - float(rng, 2, 90) * 60e3).toISOString()

    const customer: Customer = {
      id,
      villageId: village.id,
      fullName,
      phoneNumber: `+2547${String(int(rng, 0, 99999999)).padStart(8, '0')}`,
      customerType: type,
      tariffId,
      connectedAt,
      accountBalanceKes,
      arrearsKes,
      householdSize: type === 'household' ? Math.round(clamp(normal(rng, 5, 2), 1, 12)) : null,
      occupation: type === 'household' || type === 'small_business' ? pickWeighted(rng, occupations) : null,
      appliancesOwned: appliances(rng, type, tariffId),
    }

    const meter: Meter = {
      id: `mtr_${String(n).padStart(5, '0')}`,
      customerId: id,
      serialNumber: `KPLC-MG-${String(int(rng, 10000, 99999))}`,
      status: disconnected ? 'disconnected' : meterOffline ? 'offline' : 'online',
      installedAt: connectedAt,
      lastSeenAt,
      latitude: village.latitude + float(rng, -0.012, 0.012),
      longitude: village.longitude + float(rng, -0.012, 0.012),
    }

    out.push({ customer, meter })
  }
  return out
}
