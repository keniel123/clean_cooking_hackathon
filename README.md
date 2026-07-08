# GridCook AI Clean Cooking Dashboard

Static GitHub Pages dashboard for the Kenya-first clean cooking hackathon
concept (Oloika mini-grid, e-cooker trial). The dashboard is now **data-driven**:
`index.html` loads its figures from `aggregate_data.json` at runtime instead of
hard-coded constants — edit the JSON and reload to refresh, no code change.

Live site: https://keniel123.github.io/clean_cooking_hackathon/

If the URL returns 404, enable GitHub Pages once: Settings → Pages → Source
"Deploy from a branch" → branch `main` → folder `/ (root)` → Save. GitHub
usually publishes within a minute.

## Layout

```
index.html            # single-page dashboard; charts fetch aggregate_data.json
aggregate_data.json   # data source (country + Oloika mini-grid + e-cooker aggregates)
apps/                 # hackathon apps: api (GridCook REST API), dashboard
                      #   (utility monitoring UI, wired to the API), survey
                      #   (two-way SMS panel, shares the API's account IDs),
                      #   mobile, model
build/                # data pipeline
  prepare_data.py     #   builds aggregate_data.json from raw inputs (see data note)
  build_workbook.mjs  #   builds the aggregate .xlsx
  verify_workbook.mjs
analysis/             # persona grounding from the e-cooker telemetry
  analyze_personas.py #   reproduces the 176 cooking sessions; per-plug/household stats
  personas.json       #   4 personas (3 grounded in trial data + 1 synthetic restaurant)
three_day_hackathon_plan.md
```

## The dashboard presents

- Kenya clean-cooking problem framing
- Oloika mini-grid and e-cooker evidence
- cooker profiles
- health-weighted smoke-exposure proxy
- AI scheduler concept
- daytime cooking rewards
- hackathon execution plan

Four charts + a target-country table, all derived at load time from
`aggregate_data.json`. If the JSON can't be loaded (e.g. opened as a `file://`
path) the page shows an explicit error banner; for local preview serve over
HTTP: `python3 -m http.server`.

## Personas (analysis/)

`analyze_personas.py` derives cooking-session distributions from the Oloika
e-cooker trial (8 smart plugs / 5 households / 176 sessions, June 2025) and
`personas.json` encodes four personas for the "best time to cook" scheduler:

- **P1 Daytime-ready** (hh F) — frequent short daytime cooks, ~62% already in solar windows
- **P2 Evening-anchored** (hh G+H) — cooks the 20:00–22:00 peak on battery; primary shift target
- **P3 High-energy midday** (hh B) — long midday cooks, well-timed to solar
- **R1 Restaurant** — *synthetic*: no restaurant was metered; sized from an assumed
  electric appliance list (~7 kW peak, ~18 kWh/day), clearly flagged as an assumption

Baseline from the data: ~65% of cooking energy already lands in solar windows;
~35% is shiftable into daytime solar.

## Data note

The **raw household telemetry** (`HA_Oloika.sqlite`, Victron/Fronius mini-grid
exports) and the UNHCR case-study PDF are **not** included in this public repo
(household-level privacy + third-party material). `build/prepare_data.py` also
references World Bank SDG workbooks not included here, so `aggregate_data.json`
is the authoritative pre-computed source rather than a turn-key rebuild.

This is a proof-of-concept. The health section estimates reduced smoke-exposure
sessions as a proxy and does not claim medical diagnosis or measured disease
reduction.
