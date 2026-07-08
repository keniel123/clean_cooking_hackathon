import type { Customer, SurveyResponse } from '../../../domain/models'
import { chance, float, hashString, mulberry32, pick, pickWeighted } from '../random'

const POSITIVE_COMMENTS = [
  'Supply is reliable, thank you',
  'Very happy with the connection',
  'Tokens are easy to buy on M-PESA',
  'My business has grown since connection',
  'Children can now study at night',
]

const NEGATIVE_COMMENTS = [
  'Sometimes power cuts in the evening',
  'Price per unit is high for me',
  'Please add more daytime power',
  'Tokens run out too fast',
]

function satisfactionAnswers(rng: ReturnType<typeof mulberry32>): Record<string, string> {
  const rating = pickWeighted(rng, [[5, 30], [4, 40], [3, 20], [2, 10]] as const)
  return {
    rating: `${rating}/5`,
    comment: pick(rng, rating >= 4 ? POSITIVE_COMMENTS : NEGATIVE_COMMENTS),
  }
}

/** SMS survey campaigns: onboarding (always answered — it is the source of the
 * profile metadata) plus later campaigns at a ~65% response rate. */
export function buildSurveysForCustomer(
  customer: Customer,
  seed: number,
  now: Date,
  nextId: () => string,
): SurveyResponse[] {
  const rng = mulberry32((seed ^ hashString(customer.id)) + 29)
  const nowMs = now.getTime()
  const connectedMs = new Date(customer.connectedAt).getTime()
  const surveys: SurveyResponse[] = []

  const onboardingSent = new Date(connectedMs + 86400e3)
  onboardingSent.setHours(10, 0, 0, 0)
  surveys.push({
    id: nextId(),
    customerId: customer.id,
    campaign: 'onboarding',
    channel: 'sms',
    sentAt: onboardingSent.toISOString(),
    respondedAt: new Date(onboardingSent.getTime() + float(rng, 1, 48) * 3600e3).toISOString(),
    answers: {
      user_type: customer.customerType,
      ...(customer.householdSize !== null && { household_size: String(customer.householdSize) }),
      ...(customer.occupation !== null && { occupation: customer.occupation }),
      appliances: customer.appliancesOwned.join(', '),
    },
  })

  const campaigns = [
    { campaign: 'appliance_census_2026', sentAt: new Date('2026-03-10T09:00:00Z') },
    { campaign: 'satisfaction_q2', sentAt: new Date('2026-06-15T09:00:00Z') },
  ]
  for (const { campaign, sentAt } of campaigns) {
    if (sentAt.getTime() < connectedMs || sentAt.getTime() > nowMs) continue
    const responded = chance(rng, 0.65)
    const answers: Record<string, string> =
      campaign === 'appliance_census_2026'
        ? {
            appliances: customer.appliancesOwned.join(', '),
            planning_to_buy: pick(rng, ['TV', 'refrigerator', 'radio', 'nothing', 'water pump']),
          }
        : satisfactionAnswers(rng)
    surveys.push({
      id: nextId(),
      customerId: customer.id,
      campaign,
      channel: 'sms',
      sentAt: sentAt.toISOString(),
      respondedAt: responded
        ? new Date(sentAt.getTime() + float(rng, 1, 72) * 3600e3).toISOString()
        : null,
      answers: responded ? answers : {},
    })
  }
  return surveys
}

