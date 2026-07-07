# GridCook MVP Architecture

## Product Flow

GridCook connects a household user, a communal cooker, and a time window recommendation.

1. User opens the mobile app or sends an SMS.
2. API returns the user profile, credits, cooker list, and recommended cooking windows.
3. User selects a green/orange/red time and a communal cooker ID.
4. `POST /sessions/start` creates an active or reserved cooking session.
5. `POST /sessions/{id}/stop` closes the session, estimates kWh, awards credits, and releases the cooker.
6. The model uses the updated session history to refine profile and timing recommendations.

## Mobile Mockups

### Home/Profile

```text
GridCook AI

Amina N.                         Profile: evening-anchored
Credits: 84                      This month: 7.2 kWh
Green sessions: 7                Smoke-risk sessions avoided: 12

Today’s cooking windows
[10:00 GREEN +12 credits] [12:00 GREEN +14]
[15:00 ORANGE +5]         [19:00 RED +0]

Selected: 12:00-13:00
Why: High solar, battery healthy, low community load
Expected reward: +14 credits
Estimated cost: 0.28 kWh

Cooker ID
[ C-01 ] [ C-02 ] [ C-03 ]

[ GO ]
```

### Active Session

```text
Cooking on Cooker C-03

Started: 12:04
Elapsed: 18 min
Estimated kWh: 0.21
Current reward: +10 credits
Window: GREEN

[ STOP COOKING ]
```

### SMS

```text
BAL
-> You have 84 credits. This month: 7.2 kWh, 7 green sessions.

BOOK 13 C3
-> Booked Cooker C-03 at 13:00. Expected reward: +14 credits.

START C3
-> Session started on Cooker C-03. Reply STOP C3 when done.

STOP C3
-> Session closed. Estimated 0.28 kWh. Earned +14 credits.
```

## API Surface

- `GET /me`: user profile, credits, kWh, profile type, smoke-risk proxy.
- `GET /cookers`: communal cooker IDs, status, active user, elapsed time.
- `GET /recommendations`: green/orange/red slots with expected credits and reason.
- `POST /sessions/start`: starts or reserves a cooker session.
- `POST /sessions/{id}/stop`: closes a session, estimates kWh, awards credits.
- `GET /credits/ledger`: wallet history.
- `GET /leaderboard`: cohort-level leaderboard.
- `GET /operator/summary`: operator gateway status.
- `POST /sms/inbound`: JSON mock for Twilio-style SMS messages.
- `POST /sms/twilio`: form-compatible Twilio-style webhook.
- `POST /model/retrain`: manual MVP retraining hook.

## Database

The SQLite schema is Postgres-compatible in shape and contains:

- users, communities, cookers
- cooker profiles
- recommendation slots
- cooking sessions
- credits ledger
- SMS messages
- health diary entries
- grid telemetry
- model versions

The MVP estimates kWh from the cooker profile until smart-plug ingestion is connected.

## Model V0

The v0 model is deliberately explainable:

- cooker profile learning from session history
- deterministic green/orange/red grid scoring
- reward calculation from verified kWh and window color
- health proxy from e-cooking session replacement confidence

This avoids over-claiming from the small Oloika dataset while still creating a real feedback loop.
