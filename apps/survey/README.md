# eCooking SMS Panel — rural Kenyan PV minigrid

Two-way SMS panel survey studying electric cooking behaviour and daytime
load-shifting among minigrid households, per the study design in
`eCooking_SMS_Survey_Design.docx` and the question bank in
`eCooking_SMS_Survey_Question_Bank.xlsx` (the maintained design masters —
the YAML instruments in `surveys/` are transcribed from them and must be
kept in sync).

Respondents answer by replying to one SMS at a time, so everything works on
any feature phone. Completed sessions earn free electricity credits whose
validity window (daytime-only vs anytime) is randomised per household — the
credit-window experiment at the heart of the study.

Built with FastAPI + SQLAlchemy, with a **pluggable SMS gateway**:

| Provider | `SMS_PROVIDER` | Use for |
|---|---|---|
| Console | `console` | Local development — messages print to the terminal |
| Twilio | `twilio` | Testing from Europe with a UK number |
| Africa's Talking | `africastalking` | Kenya production (direct Safaricom/Airtel/Telkom routes) |

## How it works

```
cron: survey panel run ──▶ panel.py: who is due what today?
                                │ enrolment → baseline 1-3 (days 1/3/5)
                                │ → weekly pulse (4-week rotation) → monthly/quarterly
                                ▼
                          engine.py state machine ──▶ gateway ──▶ household
                                ▲                                    │ reply
                                └── /webhooks/{twilio,africastalking} ┘
```

- **Language per household**: S0 at enrolment sets English or Kiswahili; every
  later message, prompt and reward text follows that choice.
- **Consent before anything else** (S1, Kenya DPA 2019): NO ends contact
  permanently; STOP (or ACHA) works at any time and is confirmed.
- **Skip logic**: every answer is stored per-household as a named variable
  (`own_epc`, `w_midday_cooked`, ...). Questions carry `ask_if` / `skip_if`
  conditions that evaluate against these — including answers from earlier
  sessions (households with no working EPC and no hob never see W4-W7).
- **Invalid replies** follow the workbook's operating rule: SYS_INVALID once,
  then the next reply is accepted as given (stored raw, flagged
  `is_valid=False`) so sessions never get stuck.
- **Rewards**: completing a session records a pending credit (doubled for
  arm C) and sends the reward SMS — which doubles as the load-shifting nudge
  ("valid tomorrow 10am-3pm", or "any time" for control arm B). A 4-week
  completion streak earns a bonus. Export the ledger for the vending system
  with `survey rewards export`.
- **Operating rules** (implemented in `panel.py`): preferred send slot (B24),
  max one session per day, none on Sundays, 48h response window, one reminder
  at 24h, rest from the weekly pulse after 3 consecutive misses (monthly
  continues; any completion un-rests).

## Quickstart (no SMS account needed)

```bash
python3.11 -m venv .venv && source .venv/bin/activate   # 3.11+
pip install -e ".[dev]"

survey panel load                                        # load the 11 instruments
survey respondent add "0712 345 678" --account-id MTR-0042 --site Kisii
# ...or enrol every Oloika mini-grid account from the GridCook API (apps/api):
# survey respondent import-gridcook
survey panel run                                         # sends the enrolment SMS
survey reply 0712345678 "1"        # S0: Kiswahili
survey reply 0712345678 "NDIYO"    # S1: consent  → S2 + C1 arrive
survey reply 0712345678 "1"        # C1: main cook → welcome credit
survey panel status
```

Time-travel isn't scriptable from the CLI (the scheduler uses today's date),
but `tests/test_panel.py::test_panel_calendar_progression` walks the full
12-month calendar if you want to see it.

Run the API server (webhooks + dashboard endpoints):

```bash
uvicorn app.main:app --reload --port 8001   # docs at http://127.0.0.1:8001/docs
curl -X POST localhost:8001/webhooks/simulate -H 'Content-Type: application/json' \
     -d '{"from": "+254712345678", "text": "1"}'
```

(Port 8001 keeps clear of the GridCook API, which the rest of the repo runs
on 8000.)

## GridCook integration (apps/api, apps/dashboard)

This panel plugs into the repo's Oloika stack through the shared
`account_id`:

- **`survey respondent import-gridcook`** enrols every mini-grid account
  served by a GridCook API (`--base-url`, default `GRIDCOOK_API_BASE` in
  `.env`, the deployed `https://delft-api.flonat.com`). The dataset is
  privacy-preserving and has no contact details, so each respondent gets a
  deterministic placeholder phone derived from its account ID with the *same*
  FNV-1a derivation the monitoring dashboard displays (`app/gridcook.py` ↔
  `apps/dashboard/src/data/http/HttpDataProvider.ts`) — account ID and phone
  line up across apps end to end.
- **`GET /api/respondents/{account_id}/responses`** returns one account's
  survey history (sessions + answers keyed by codebook variable). The
  dashboard's customer page renders it when `VITE_SURVEY_API_BASE_URL` points
  here; CORS is enabled for GET so the browser can call it directly.

## Handset demo

For live demonstrations, **http://127.0.0.1:8000/demo** renders a classic
feature phone whose keypad drives the real engine — consent, skip logic and
rewards behave exactly as they would on a respondent's handset.

- Click **Reset demo** (registers the respondent and loads the instruments on
  a fresh DB), pick an instrument, **Send survey**, and reply on the keypad.
- The keypad starts in `123` mode (surveys are numeric; `*` types the comma
  for multi-select replies like `1,3`). Press `#` for authentic multi-tap
  `abc` mode — or just type on your computer keyboard; Enter sends.
- The side panel shows the operator's view live: language, consent, arm,
  the question the session is waiting on, recorded variables and earned
  credits — useful for narrating skip logic ("`own_epc=3` was just recorded,
  so watch W4 get skipped in the next pulse").
- A suggested demo script is printed under the panel.

The demo (like `/webhooks/simulate`) only exists while `ENABLE_SIMULATOR=true`
— disable it in production.

Tests: `pytest` (68 tests: engine, instruments, panel calendar, webhooks,
loader, phones, GridCook import + responses API).

## Operating the panel

1. Configure `.env` from `.env.example`. Set `UTILITY_NAME` (substituted into
   `{utility}` in S0) and check `TIMEZONE` (default Africa/Nairobi).
2. Import households: `survey respondent import households.csv`
   (columns: phone,account_id,name,site,language), or pull them from the
   GridCook API with `survey respondent import-gridcook`. `account_id` is the
   join key to smart-meter data — always set it.
3. Load instruments: `survey panel load`
4. Schedule the dispatcher (respects each household's B24 preference):
   ```cron
   0 7  * * *  survey panel run --slot morning
   0 12 * * *  survey panel run --slot midday
   0 19 * * *  survey panel run --slot evening
   ```
5. After baseline 2 responses arrive, randomise the experiment:
   `survey panel assign-arms --seed 2026` (A/B/C = 40/40/20, stratified by
   village × EPC ownership).
6. Weekly: `survey rewards export pending.csv`, load the credits into the
   vending system (arms A/C as daytime-window tokens, arm B unrestricted),
   then `survey rewards mark-delivered`. Reconcile against W7 option 4
   ("I did not get units") — it is the delivery-failure detector.
7. Export data per instrument: `survey export ecooking-baseline-2 out.csv`.
   Columns are codebook variable names; values are numeric codes — join the
   workbook's Codebook sheet for labels. Invalid-but-accepted replies appear
   as `INVALID:<raw text>`.

## Instrument YAML schema

```yaml
slug: ecooking-pulse-week-1
title: Weekly pulse — week 1 rotation
module: weekly          # enrolment|baseline|weekly|monthly|quarterly|rebaseline|adhoc
reward_kwh: 0.4         # credit on completion (0 = send `thanks` text instead)
questions:
  - key: W3             # QID from the question bank
    var: w_midday_barrier   # codebook variable (export column, condition target)
    type: single        # single | multi | number | yesno | text | system
    choices: 5          # single/multi: valid replies are 1..choices
    ask_if: [{var: w_midday_cooked, equals: 2}]     # ANDed; also: not_equals, in, contains
    text:               # exact SMS per language, sent verbatim (≤160 GSM-7 chars)
      en: "What stopped you cooking at midday yesterday? 1=..."
      sw: "Nini kilikuzuia kupika mchana jana? 1=..."
```

Also available: `min`/`max` (number), `skip_if` (skip when all match),
`sets` (answer updates a respondent attribute — S0 sets `language`, B24 sets
`preferred_send_time`), `end_if` (end the survey early on a given answer —
S1 consent refusal). `system` steps are sent without expecting a reply.
`survey panel load` warns if any text exceeds one SMS segment, and refuses
to modify a survey that has ever been dispatched (create a new slug).

## Gateway setup

**Twilio (UK testing from Europe):** buy a UK number, set
`SMS_PROVIDER=twilio`, `DEFAULT_COUNTRY=GB`, the three `TWILIO_*` vars, run
`ngrok http 8000`, and point the number's inbound webhook at
`https://<host>/webhooks/twilio`. Set `TWILIO_VALIDATE_SIGNATURE=true` +
`PUBLIC_BASE_URL` outside local testing.

**Africa's Talking (Kenya production):** start in the sandbox
(`AT_ENVIRONMENT=sandbox` + their simulator). Production two-way SMS needs a
**dedicated shortcode** (alphanumeric sender IDs cannot receive replies);
operator approval is slow — start early. Point the inbound callback at
`https://<host>/webhooks/africastalking`, then set `SMS_PROVIDER=africastalking`,
`DEFAULT_COUNTRY=KE`, `ENABLE_SIMULATOR=false`.

## Compliance (Kenya DPA 2019)

Consent is collected by SMS before any question and logged with a timestamp
against the account ID; STOP/ACHA cancels instantly and is honoured forever;
unknown numbers are never replied to. Before analysis sharing: pseudonymise
phone numbers, and review Q6 free-text replies for personal details. The
operator should confirm ODPC registration.

## Project layout

```
app/
  engine.py           state machine: verbatim bilingual texts, validation,
                      ask_if/skip_if conditions, variable store, sets/end_if
  panel.py            panel calendar, reminders/expiry, resting, arm assignment
  rewards.py          credit ledger + reward/nudge messages per arm
  models.py           Respondent, RespondentVariable, Survey, Question,
                      SurveySession, Answer, Reward, MessageLog
  survey_loader.py    YAML instruments → DB, with 160-char segment checks
  results.py          per-session export keyed by codebook variables
  gridcook.py         enrol GridCook API accounts (dashboard-parity phones)
  gateways/           console | twilio | africastalking behind one interface
  routes/             inbound webhooks + read API
  cli.py              `survey` command (panel, respondents, rewards, export)
surveys/              the 11 instruments + panel.yaml calendar
tests/                60 tests incl. full enrolment flow and 12-month calendar
```

## Known gaps before launch

- **Pilot items from the design are not code**: comma-separated multi-select
  comprehension, Kiswahili dialect review, dual clock-convention phrasing —
  test with 20-30 households and revise the YAMLs (before first dispatch).
- **Credit delivery is manual** (CSV export/import) until the vending system
  API is specified; W7=4 monitoring is the safety net.
- **Q1→B1 re-ask** happens at the end of the same quarterly session, not the
  "next session" as the workbook says — one message cheaper, data equivalent.
- **Month-12 layout**: the re-baseline replaces the week-3 pulse, quarterly
  runs in week 4 as usual.
- **No auth on the HTTP API** — keep it private-network-only.
- **Postgres + Alembic** before real data: set `DATABASE_URL`, add migrations.
- Per-question non-response and invalid-rate monitoring (design §6) is
  queryable from `answers`/`message_log` but has no dashboard yet.
