# GridCook AI: 3-Day Hackathon Build Plan

## What To Build

Build a proof-of-concept called **GridCook AI**: a mini-grid aware clean-cooking dashboard and scheduler demo.

The core idea is not to solve all clean cooking in 3 days. The goal is to prove that AI can help mini-grid operators and clean-cooking programs decide:

1. Where to prioritize clean-cooking pilots.
2. When households should be nudged to use electric cooking.
3. Whether the mini-grid has enough headroom for adoption.
4. What evidence funders need to support a field pilot.

## Final Demo Output

By the end of day 3, the team should present:

1. A dashboard with clean-cooking access gap, target countries, Oloika mini-grid energy, and e-cooker usage charts.
2. A simple AI scheduler simulation that recommends cooking windows based on battery SOC, PV generation, load, and observed cooking behavior.
3. A clear 6-slide pitch for the Clean Cooking Alliance.
4. A realistic implementation roadmap and budget for the next 8-10 weeks and a 6-month field pilot.

## Chosen Pilot: Kenya

Make the hackathon proposal Kenya-first. The reason is simple: Kenya has a large clean-cooking gap, electricity access is much higher than clean-cooking access, and the data folder includes Oloika mini-grid and e-cooker telemetry that can make the demo concrete.

Use these numbers in the pitch:

- Kenya clean-cooking access: 31.6% in 2023.
- Kenya population without clean cooking: about 37.9M people.
- Kenya rural clean-cooking access: 10.4% in 2022.
- Kenya electricity access: 76.0% in 2022.
- Oloika e-cooker trial evidence: 176 valid cooking sessions, 46.0 kWh measured e-cooker energy, 2.1 kW peak observed appliance power.
- Oloika mini-grid context: 1,626.1 kWh June AC consumption, with e-cooker trial load equal to about 2.8% of site AC consumption.

The framing:

> Kenya does not only need more clean-cooking appliances. It needs a way to place e-cooking where electricity exists, schedule cooking so mini-grids do not overload, and prove adoption impact to funders.

## MVP Scope

### Must Have

- Dashboard with KPIs and charts from the provided datasets.
- Kenya/Oloika-first problem framing.
- Session timing chart from smart-plug data.
- Mini-grid daily load/PV chart.
- Target-country prioritization table.
- AI use-case section explaining forecast, schedule, target, detect, and measure.
- Cooker Profile demo showing habitual cooking windows, average kWh/session, session frequency, flexibility, and reward responsiveness.
- Mock scheduler output: "Recommended clean-cooking windows" for a sample day.
- Daytime Cooking Rewards demo: points, household credits, and community leaderboard for cooking in green windows.
- Pitch story and judge-criteria mapping.

### Nice To Have

- Simple interactive controls for number of households or appliance adoption rate.
- Mock SMS/WhatsApp message examples.
- Before/after impact estimate for biomass displacement.
- Basic anomaly flag for low voltage or low battery SOC periods.
- Mock reward wallet showing earned cooking credits.
- Profile cluster labels such as "daytime-ready", "evening-anchored", "high-energy", or "low-use".

### Do Not Build

- A production mobile app.
- Real-time IoT ingestion.
- Deep learning model training.
- Payment systems.
- Real cash-out or mobile-money integrations.
- Hardware integration.
- Full carbon accounting.

## Literal Kenya Build Runbook

Use this as the team's task list. The MVP should feel like something a Clean Cooking Alliance program officer and a Kenyan mini-grid operator could understand immediately.

### Step 0: Set The Working Assumptions

1. Choose Kenya as the only implementation country for the hackathon demo.
2. Choose Oloika as the proof site because the folder contains local mini-grid and e-cooker telemetry.
3. Define the end user as a mini-grid operator plus a clean-cooking program manager.
4. Define the intervention as electric pressure cookers or efficient e-cooking appliances on mini-grids.
5. Define the AI output as recommended cooking windows, grid-risk alerts, and pilot targeting evidence.
6. Define a cooker profile as an anonymized household/appliance profile, not a public identity.
7. State that this is a proof-of-concept using historical data, not a live control system.

### Step 1: Build The Data Inventory

Create one source table that says what each file contributes:

- `sdg7.1.2_-_clean_cooking.xlsx`: clean-cooking access by country and year.
- `sdg7.1.1_-_access_to_electricity.xlsx`: electricity access by country and year.
- World Bank population data: population used to convert percentages into people affected.
- `HA_Oloika.sqlite`: smart-plug appliance readings used to detect e-cooker sessions.
- `OloikaMinigridUniversityofSouthampton_Victron_June_2025.csv`: mini-grid load, battery, and inverter context.
- `OLOIKA_MINIGRID-MAGADI_FRONIUS_June_2025.xlsx`: solar PV generation context.
- `UNHCR-Case-Study.pdf`: deployment lessons on behavior change, safety, logistics, and monitoring.

Output: a one-page "data dictionary" with source, time period, useful fields, and limitations.

### Step 2: Clean And Aggregate Kenya Indicators

1. Filter clean-cooking data to Kenya.
2. Pull latest clean-cooking access value available in the dataset.
3. Pull Kenya population for the same year.
4. Calculate people without clean cooking:
   `population * (1 - clean_cooking_access_percent / 100)`.
5. Pull Kenya electricity access.
6. Pull rural clean-cooking access if available.
7. Put these values into the dashboard KPI cards and slide 1.

Output: a verified Kenya indicators table with access, population, gap, and data year.

### Step 3: Convert Oloika Smart-Plug Data Into Cooking Sessions

1. Load smart-plug power readings from `HA_Oloika.sqlite`.
2. Convert timestamps to a consistent timezone. Use Africa/Nairobi for the pitch.
3. Filter to active e-cooker plugs.
4. Detect a cooking session when power rises above a practical threshold for multiple consecutive readings.
5. Merge readings into one session if the off-gap is short, for example under 5 minutes.
6. Calculate each session's start time, end time, duration, peak watts, and kWh.
7. Remove obvious noise, such as extremely short spikes or impossible power values.
8. Aggregate sessions by hour of day and by household or plug.

Output: `cooking_sessions.csv` with one row per session.

Minimum fields:

- `session_id`
- `plug_id`
- `household_id` if available, otherwise anonymized plug group
- `start_time`
- `end_time`
- `duration_minutes`
- `energy_kwh`
- `peak_watts`
- `start_hour`

### Step 4: Generate Cooker Profiles

Purpose: learn how each participating household or appliance usually cooks so the scheduler can recommend realistic green windows instead of generic instructions.

Inputs:

- `cooking_sessions.csv`
- smart-plug or appliance ID
- household ID if consented, otherwise anonymized profile ID
- optional survey fields from a future pilot, such as preferred meal times, household size, and ability to shift cooking
- reward history once the incentive layer starts

Profile features to generate:

- `profile_id`
- `plug_id`
- `sessions_per_week`
- `avg_session_kwh`
- `median_session_minutes`
- `p95_peak_watts`
- `usual_breakfast_window`
- `usual_lunch_window`
- `usual_dinner_window`
- `green_window_share`
- `night_peak_share`
- `avg_points_per_week`
- `reward_response_score`
- `flexibility_score`
- `adoption_trend`
- `anomaly_baseline`

How to learn the profiles in 3 days:

1. Group cooking sessions by anonymized plug or household.
2. Calculate average kWh, median duration, peak wattage, sessions per week, and common start hours.
3. Use simple rules or k-means clustering to label profile types:
   - `daytime-ready`: already cooks often during high-solar hours.
   - `evening-anchored`: mostly cooks after sunset and needs stronger incentives.
   - `high-energy`: uses more kWh per session and needs grid-headroom checks.
   - `low-use`: has the appliance but is not yet adopting e-cooking regularly.
   - `irregular`: needs more data before personalization.
4. Calculate a flexibility score:
   `share_of_sessions_outside_peak + historical_daytime_share + reward_response`.
5. Store a small `cooker_profiles.csv` table for the dashboard and scheduler.

How profiles improve the product:

- Scheduler: recommends windows that match each household's real cooking rhythm.
- Rewards: offers higher points to households that need more incentive to shift daytime.
- Grid protection: estimates likely added load from high-energy profiles.
- Adoption monitoring: flags households that stop using the appliance.
- Maintenance: flags unusual power shapes or rising energy use that may mean appliance or wiring issues.

Privacy guardrails:

- Use anonymized profile IDs in the hackathon dashboard.
- Never publish individual household rankings.
- Show public leaderboard only at cohort/community level.
- Explain that a real pilot needs consent, clear data retention rules, and opt-out.

Output: `cooker_profiles.csv` with one row per household/appliance profile.

### Step 5: Build The Mini-Grid Hourly Table

1. Load Victron mini-grid telemetry.
2. Load Fronius PV generation telemetry.
3. Aggregate all telemetry to hourly rows.
4. Create these feature columns:
   - `timestamp_hour`
   - `ac_load_kwh`
   - `pv_kwh`
   - `battery_soc_avg`
   - `battery_soc_min`
   - `voltage_min` if available
   - `ecook_sessions`
   - `ecook_kwh`
   - `hour_of_day`
   - `day_of_week`
5. Join cooking sessions onto the hourly mini-grid table.
6. Add rolling features:
   - previous-hour load
   - 3-hour rolling load
   - 3-hour rolling PV
   - previous-hour cooking sessions
7. Validate totals against the known metrics:
   - 46.0 kWh e-cooker energy
   - 176 valid sessions
   - 1,626.1 kWh June AC consumption

Output: `model_hourly_oloika.csv`, the one table used for all AI demos.

### Step 6: Train Model 1, Cooking Demand Forecast

Purpose: estimate how much e-cooking demand is likely in each hour.

Target options:

- Simple target: `ecook_sessions_next_hour`.
- Better target: `ecook_kwh_next_hour`.

Features:

- hour of day
- day of week
- previous-hour cooking sessions
- previous-hour e-cooking kWh
- 3-hour rolling cooking sessions
- profile type
- profile average session kWh
- profile flexibility score
- current or forecast PV kWh
- current or forecast battery SOC
- current or forecast AC load

Model to train in the hackathon:

- Start with a baseline: average sessions by hour of day.
- Then train a simple interpretable model: linear regression, random forest, or gradient boosting if available.
- If the dataset is too small, keep the rule-based hourly average and explain that a field pilot will collect more labels.

Train/test method:

1. Use June 1-23 as training data.
2. Use June 24-30 as validation data.
3. Compare model MAE against the hour-of-day baseline.
4. Show one chart: predicted versus actual hourly cooking sessions.

What to say to judges:

> We are not claiming deep learning performance from a small dataset. We use a transparent forecast now, and the pilot turns the model into a better site-specific predictor as more households join.

### Step 7: Train Model 2, Grid Risk Classifier

Purpose: label each hour as green, yellow, or red for e-cooking.

Create labels from engineering rules:

- Green: battery SOC is healthy, PV is available or load is low, and voltage is safe.
- Yellow: battery SOC is moderate, load is near peak, or PV is uncertain.
- Red: battery SOC is low, load is near peak, or voltage risk is detected.

Suggested hackathon thresholds:

- Green if `battery_soc_avg >= 50` and `ac_load_kwh` is below the 75th percentile.
- Yellow if `battery_soc_avg` is 35-50 or `ac_load_kwh` is between the 75th and 90th percentile.
- Red if `battery_soc_avg < 35`, `ac_load_kwh` is above the 90th percentile, or voltage is below a safe threshold.

Model to train in the hackathon:

- Train a shallow decision tree or logistic classifier on these labels.
- Keep the rules visible in the dashboard so the model is explainable.
- If model training adds confusion, present the rules as the MVP and list the classifier as the next step.

Validation:

- Show a confusion matrix against the rule labels.
- Prioritize red-hour recall over overall accuracy.
- Explain that real safety labels need operator validation in the field.

Output: a function that returns `green`, `yellow`, or `red` for each hour.

### Step 8: Build The Scheduler Simulation

Purpose: turn forecasts and grid-risk labels into action.

Inputs:

- forecast cooking sessions by hour
- forecast or observed PV
- forecast or observed battery SOC
- AC load headroom
- number of participating households
- cooker profile type and flexibility score
- average e-cooker session energy, using Oloika's observed average of about 0.26 kWh per session
- appliance peak power, using observed peak around 2.1 kW as the conservative planning value

Scheduler logic:

1. Score each hour from 0 to 100.
2. Add points for high battery SOC and available PV.
3. Remove points for high AC load, low SOC, and voltage risk.
4. Mark hours as green, yellow, or red.
5. Allocate suggested cooking batches to green hours first.
6. Cap added load so the recommendation does not exceed mini-grid headroom.
7. Use cooker profiles to avoid recommending impossible windows to households with rigid routines.
8. Add a fairness rule: do not always push the same households into inconvenient hours.

Output shown in the dashboard:

- recommended cooking windows
- estimated households per window
- expected added kWh
- avoided red-window cooking sessions
- profile-specific nudge examples
- warning if the grid does not have enough headroom

### Step 9: Build The Daytime Cooking Rewards Layer

Purpose: make the scheduler behavior change real. The product should not just tell households when to cook; it should make daytime/green-window cooking feel financially worth it.

Core idea:

> Households earn cooking credits when they cook in green windows, get small partial points in yellow windows, and get no reward in red windows. The leaderboard is community/team-based, while individual household rewards stay private.

Why this matters:

- Mini-grids often have more usable solar power during the day.
- Cooking demand can stack in the evening when batteries are lower and household loads rise.
- A reward system shifts behavior without forcing households to obey the scheduler.
- It creates a funder-friendly metric: "percentage of e-cooking moved into green hours."

Reward formula for the hackathon demo:

```text
reward_points =
  verified_ecook_kwh
  * window_multiplier
  * fairness_multiplier
  + streak_bonus
```

Suggested multipliers:

- Green window: `10 points per kWh`.
- Yellow window: `3 points per kWh`.
- Red window: `0 points`.
- First-time daytime cooking bonus: `+5 points`.
- Weekly consistency bonus: `+10 points` after 3 green-window cooking days.
- Fairness multiplier: boost households with fewer previous reward opportunities so the same people do not always win.

Reward types:

- Electricity bill credit.
- Appliance repayment discount.
- Cooking ingredient voucher.
- Airtime voucher.
- Community prize, such as a shared appliance-maintenance fund.

Leaderboard design:

- Show public rankings by village group, savings circle, or appliance cohort.
- Keep household-level scores private in the household's wallet.
- Show progress toward community targets, for example "70% of cooking sessions this week happened in green windows."
- Avoid public shaming for households that cook at night because of work, school, caregiving, or safety constraints.

Anti-gaming rules:

1. Reward only verified e-cooker sessions, not random plug usage.
2. Require plausible cooking duration and power shape.
3. Cap points per household per day.
4. Do not reward repeated very short sessions.
5. Flag abnormal usage for operator review.
6. Keep an opt-out option so the system remains voluntary.

Data needed in the MVP:

- session start time
- session kWh
- assigned grid window: green, yellow, red
- household or plug ID
- cooker profile type
- daily points
- weekly points
- redeemed credits

Output shown in the dashboard:

- sample community leaderboard
- private household wallet mockup
- points earned this week
- estimated bill credit
- percentage of cooking shifted from red/yellow windows into green windows

What to say to judges:

> The financial incentive is not a gimmick. It converts the AI scheduler into behavior change. The operator benefits from lower evening peak stress, households benefit from lower effective cooking cost, and funders get measurable adoption evidence.

### Step 10: Build The Dashboard

The dashboard should have these exact sections:

1. Kenya problem KPI cards.
2. Addressable population chart.
3. Oloika mini-grid energy chart.
4. E-cooker session timing chart.
5. Cooker Profiles panel with habitual cooking windows, kWh/session, flexibility, and adoption trend.
6. AI scheduler panel with green/yellow/red windows.
7. Daytime Cooking Rewards panel with leaderboard and household credits.
8. "What AI does" cards.
9. Implementation plan and budget assumptions.
10. Risks and mitigations.

Do not make the dashboard a generic website. It should feel like a funding evidence pack.

### Step 11: Build The Pitch Story

Use this sequence:

1. Kenya has a large clean-cooking gap.
2. Electricity access is much higher than clean-cooking access, so e-cooking can be targeted.
3. Mini-grids can support e-cooking only if load is managed.
4. Oloika data shows real e-cooker usage and real grid constraints.
5. Cooker Profiles learn each household's normal cooking rhythm and energy use.
6. GridCook AI forecasts demand and recommends safe cooking windows.
7. Daytime Cooking Rewards gives households a financial reason to follow green cooking windows.
8. The MVP can be built without new hardware.
9. The field pilot tests adoption, affordability, reliability, and impact.

### Step 12: Define The Funding Ask

Use these as proposal assumptions, not final procurement quotes:

- 8-10 week MVP: about USD 45k-70k for data engineering, dashboard, scheduler, field design, and stakeholder review.
- 6-month Kenya pilot: about USD 120k-220k, excluding major grid upgrades and depending on appliance finance/subsidies/reward budget.
- Pilot size: 50-150 households across one to three mini-grid communities.
- Success metrics: e-cooking sessions per household, green-window cooking share, red-window avoidance, reward redemption, reduced biomass/charcoal use, appliance retention, user satisfaction, and operator confidence.

## What We Actually Train In 3 Days

Train only lightweight, explainable models. The judges should see that the team understands implementation risk.

### Train Now

1. **Cooker profile learning**
   - Input row: one verified cooking session.
   - Target: no supervised target needed for MVP.
   - Model: feature aggregation plus simple rule labels or k-means clustering.
   - Metric: profile coverage, profile stability, and whether each profile has enough sessions to personalize.

2. **Cooking demand forecast**
   - Input row: one mini-grid hour.
   - Target: next-hour e-cooking sessions or e-cooking kWh.
   - Model: baseline hourly average plus simple regression/tree model.
   - Metric: MAE versus baseline.

3. **Grid risk classifier**
   - Input row: one mini-grid hour.
   - Target: green/yellow/red status based on safety rules.
   - Model: shallow decision tree or transparent rule model.
   - Metric: red-hour recall and confusion matrix.

4. **Scheduler optimizer**
   - This is not trained. It is a constraint-based algorithm using model outputs.
   - Metric: percent of sessions recommended into green windows, max added load, and reward cost per shifted kWh.

5. **Reward scoring**
   - This is not trained. It is a transparent points formula tied to verified e-cooker kWh and green/yellow/red windows.
   - Metric: green-window share, household participation, redemption rate, and daily reward budget.

### Do Not Train Now

1. A deep learning model.
2. A household adoption model with fake labels.
3. A carbon-credit model.
4. A production recommendation model that directly controls appliances.
5. A real payment or mobile-money model.
6. A sensitive personal-profile model that uses names, exact locations, income, or family details in the public demo.

### Train Later In The Field Pilot

1. Household adoption propensity, using real appliance uptake and usage labels.
2. Fuel-stacking classifier, using surveys plus e-cooker telemetry.
3. Site-transfer model, using telemetry from multiple Kenyan mini-grids.
4. More reliable PV/load forecasting, using longer weather and grid history.

## Six-Person Team Roles

### Person 1: Product Lead and Pitch Owner

- Owns the story, problem framing, and final deck.
- Maps every slide to judging criteria.
- Keeps scope tight when the team overbuilds.
- Final deliverable: 6-slide pitch and 90-second demo script.

### Person 2: Data Lead

- Owns data cleaning and metric definitions.
- Extracts clean-cooking access, electricity access, population gap, Oloika e-cooker usage, and mini-grid daily energy.
- Builds `cooking_sessions.csv` and `cooker_profiles.csv`.
- Documents assumptions and limitations.
- Final deliverable: verified metrics table, profile table, and source notes.

### Person 3: AI/Model Lead

- Builds the simple scheduler logic.
- Inputs: hour, AC load, PV, battery SOC, observed cooking session demand, and cooker profile.
- Output: green/yellow/red cooking windows, recommended household batch size, and reward points per session.
- Final deliverable: scheduler logic and explanation diagram.

### Person 4: Dashboard/Frontend Lead

- Owns the HTML dashboard.
- Adds charts, cooker profiles, AI-use sections, target table, reward panel, and scheduler simulation panel.
- Makes sure the dashboard looks presentable on projector.
- Final deliverable: working local dashboard.

### Person 5: Impact and Business Lead

- Owns target population, expected impact, costs, and scale path.
- Estimates 8-10 week MVP and 6-month field pilot budget.
- Designs the reward budget, redemption rules, and fairness guardrails.
- Connects the idea to Clean Cooking Alliance funding logic.
- Final deliverable: impact slide and cost/time horizon.

### Person 6: QA/Demo Lead

- Tests the dashboard and demo flow.
- Checks whether numbers match the workbook.
- Prepares fallback screenshots in case the dashboard fails.
- Final deliverable: final demo checklist and backup images.

## Day 1: Frame and Prepare

### Morning

1. Agree the one-sentence concept:
   "GridCook AI helps mini-grid operators expand electric cooking by predicting safe cooking windows and proving clean-cooking impact."
2. Lock the target user:
   Mini-grid operator plus Clean Cooking Alliance program officer.
3. Lock the pilot geography:
   Kenya first, using Oloika telemetry as proof-of-concept evidence.
4. Decide the final demo:
   Dashboard -> scheduler simulation -> funding pitch.

### Afternoon

1. Data lead prepares metrics:
   - Kenya clean-cooking access.
   - Kenya population without clean cooking.
   - Rural clean-cooking gap.
   - Oloika e-cooker kWh and sessions.
   - Mini-grid AC consumption, PV, battery SOC.
   - First pass of anonymized cooker profiles.
2. AI lead defines scheduler rules:
   - Green window: battery SOC >= 50%, PV high, load below P95.
   - Yellow window: battery SOC 35-50% or load near P95.
   - Red window: battery SOC < 35%, load near peak, or voltage risk.
3. Impact lead defines reward rules:
   - Green window earns full points.
   - Yellow window earns partial points.
   - Red window earns no points.
   - Daily point caps prevent gaming.
   - Public leaderboard is community/team-based, not household-shaming.
4. Dashboard lead creates page structure.
5. Product lead drafts pitch outline.

### End Of Day 1 Output

- Clean data loaded.
- `cooker_profiles.csv` draft exists.
- Dashboard skeleton exists.
- Scheduler rules written.
- Reward rules written.
- Pitch outline exists.

## Day 2: Build

### Morning

1. Dashboard lead adds charts:
   - Top countries by clean-cooking gap.
   - Mini-grid daily energy.
   - Cooking sessions by hour.
   - Cooker profile cards.
   - Target-country readiness.
2. AI lead builds the scheduler simulation:
   - Use daily/hourly data.
   - Use profile type and flexibility score.
   - Produce recommended cooking windows.
   - Show suggested household batch size.
   - Calculate reward points and expected bill credit.
3. Dashboard lead adds the Daytime Cooking Rewards panel:
   - Community leaderboard.
   - Private household wallet mockup.
   - Green-window cooking share.
   - Reward redemption assumption.
4. Data lead validates all values.

### Afternoon

1. Impact lead writes:
   - Addressable population.
   - Expected benefits.
   - Cost and time horizon.
   - Risks and mitigations.
2. Product lead turns the story into slides.
3. QA lead tests dashboard and records screenshots.
4. Everyone does a 5-minute internal demo.

### End Of Day 2 Output

- Dashboard mostly complete.
- Cooker profile demo works.
- Scheduler simulation works.
- Daytime rewards demo works.
- Draft pitch deck complete.
- Known issues list exists.

## Day 3: Polish and Present

### Morning

1. Fix only demo-critical issues.
2. Tighten the AI explanation:
   - Forecast cooking load.
   - Learn household/appliance cooking profiles.
   - Optimize cooking windows.
   - Incentivize daytime cooking with rewards.
   - Detect grid risk.
   - Measure adoption and impact.
3. Add clear assumptions:
   - Data is historical.
   - Scheduler is a simulation.
   - Field validation is required.

### Afternoon

1. Rehearse the full demo at least 3 times.
2. Assign speaking parts:
   - Problem and market.
   - Data and evidence.
   - AI demo.
   - Impact and funding ask.
3. Prepare backup:
   - Static screenshots.
   - Workbook link.
   - One-page summary.

### Final Output

- 6-slide pitch.
- Dashboard.
- Cooker Profiles demo.
- Scheduler simulation.
- Daytime Cooking Rewards demo.
- Source workbook.
- Backup screenshots.

## Suggested 6-Slide Deck

1. **The Problem**
   - 2.06B people globally lack clean cooking.
   - Kenya has about 37.9M people without clean cooking.

2. **Why Current Pilots Fail**
   - Appliances alone do not solve affordability, timing, grid capacity, or behavior change.

3. **Our Solution**
   - GridCook AI predicts safe cooking windows and uses rewards to shift cooking into high-solar hours without overloading mini-grids.

4. **Proof From The Data**
   - Oloika e-cooker sessions, cooker profiles, mini-grid load, PV production, battery SOC, and target-country prioritization.

5. **AI Demo**
   - Show cooker profiles, green/yellow/red cooking windows, household recommendations, and Daytime Cooking Rewards.

6. **Implementation Ask**
   - Fund an 8-10 week MVP and 6-month Kenya pilot.

## Demo Script

1. "Clean cooking is still unavailable for billions, but the bottleneck is not only fuel or appliances."
2. "We focused on Kenya because the access gap is large and we have real Oloika mini-grid/e-cooker data."
3. "This dashboard shows where the need is, what the mini-grid can handle, and when cooking sessions happen."
4. "We then learn anonymized cooker profiles: who tends to cook in the morning, who cooks mostly after sunset, and which appliances consume more energy per meal."
5. "Our AI scheduler turns those profiles into realistic recommended cooking windows for households and operators."
6. "The reward layer gives households bill credits or vouchers for cooking in green windows, so the AI recommendation becomes an actual behavior-change mechanism."
7. "In a field pilot, this would reduce peak risk, improve adoption, and create funder-grade evidence."

## Judge-Criteria Fit

- **Problem relevance:** directly targets lack of clean cooking.
- **AI implementation:** uses cooker profiling, forecasting, scheduling, incentive optimization, anomaly detection, and impact monitoring.
- **Impact potential:** starts in Kenya, scales to East Africa.
- **Feasibility:** uses existing smart-plug and mini-grid data; no new hardware needed for proof of concept.
- **Presentation:** dashboard plus pitch plus implementation plan.
