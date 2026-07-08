# KPLC Microgrid Monitor

Monitoring dashboard for solar PV + battery microgrids in rural Kenya, built for
the Kenya Power and Lighting Company. Utility staff get a fleet-level overview of
all village microgrid sites and can drill down to individual customer profiles
(enriched with SMS-survey metadata).

## Running

Requires Node.js 20+.

```sh
npm install
npm run dev        # dev server at http://localhost:5173, seeded mock data
npm run dev:api    # live data from a local GridCook API (apps/api) on :8000
npm run dev:live   # live data from the deployed API at delft-api.flonat.com
npm run build      # typecheck (tsc -b) + production build to dist/
```

Setting `VITE_API_BASE_URL` (which is all `dev:api` / `dev:live` do) switches the
app from the seeded mock dataset to a live [GridCook Oloika API](../api/) — see
[Data sources](#data-sources) below. `VITE_SURVEY_API_BASE_URL` additionally
points at the [SMS survey panel](../survey/) (`dev:api` assumes it on :8001,
next to the GridCook API on :8000).

## Pages

- `/` — fleet overview: KPI cards, interactive map of sites, revenue collections, villages table
- `/villages/:villageId` — one site: energy & battery charts, revenue, M-PESA payments, arrears, searchable customer list
- `/customers/:customerId` — one customer: account & tariff, meter, consumption, payments, SMS survey profile & history

The `?range=24h|7d|30d|90d` query param drives every time-series view and is shareable.

## Languages

The UI is available in **English and Swahili** — toggle with the EN/SW switch in
the header (persisted in `localStorage`). Translations live in
[src/i18n/translations.ts](src/i18n/translations.ts): `en` is the source of truth
and the `Messages` type forces `sw` to cover every key, so a missing translation
is a compile error. Number, currency, date, and relative-time formatting follow
the active language via `Intl` (see [src/lib/format.ts](src/lib/format.ts)).
Data content (customer names, occupations, raw SMS answers) is intentionally not
translated — it will come from the backend as-is.

## Data sources

All data flows through the `DataProvider` interface
([src/data/DataProvider.ts](src/data/DataProvider.ts)); nothing in `src/pages/`
or `src/components/` knows which implementation is behind it.
[src/main.tsx](src/main.tsx) picks the implementation: `HttpDataProvider` when
`VITE_API_BASE_URL` is set, `MockDataProvider` otherwise.

- **`MockDataProvider`** ([src/data/mock/](src/data/mock/)) — deterministic,
  seeded fake data (10 villages, ~950 customers, 90 days of hourly telemetry,
  M-PESA payments, SMS surveys). Default; runs with no backend.
- **`HttpDataProvider`** ([src/data/http/](src/data/http/)) — the repo's
  [GridCook Oloika API](../api/), which serves one community (the Oloika
  mini-grid, Kajiado County) for June 2025. The mapping onto this dashboard's
  fleet-oriented domain: the `oloika` community becomes a fleet of one village;
  mini-grid accounts become customers (names/balances from the leaderboard and
  credit ledger); `/grid/hourly` telemetry drives the energy charts;
  billing-ledger `top_up` events are the payments/revenue; per-account
  daily-behavior and cooking sessions drive the consumption chart; and the
  household / commercial persona records surface as the SMS-survey profile.
  When `VITE_SURVEY_API_BASE_URL` points at the [SMS panel service](../survey/)
  and the account is enrolled there (`survey respondent import-gridcook`), the
  customer page shows the account's *real* survey sessions from
  `GET /api/respondents/{account_id}/responses` instead; if the service is
  down or the account unenrolled, it falls back to the persona record.
  Time ranges are anchored to the newest telemetry hour (June 30 2025), not the
  wall clock. Fields the privacy-preserving dataset genuinely lacks (phone
  numbers, meter serials) are synthesized deterministically and flagged inline;
  arrears are always zero because the ledger is prepaid-only.

The domain types in [src/domain/models.ts](src/domain/models.ts) double as the
proposed DB/API schema (prefixed IDs, explicit FKs, ISO-8601 timestamps, units
in field names).

## Stack

React 19 · Vite · TypeScript (strict) · Tailwind CSS v4 · React Router ·
Recharts · Leaflet (OpenStreetMap tiles)
