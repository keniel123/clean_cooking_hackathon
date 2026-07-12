# GridCook Code Review

> **Status — updated 2026-07-12.** This is the automated multi-persona code review run on 2026-07-09
> (branch `dev` @ 3cb3884). Since then the cheap, safe findings have been fixed and deployed:
>
> | Findings | Disposition |
> |---|---|
> | #8/#27, #6, #20, #11 | ✅ **Fixed** — PR #16 (batch 1): transaction-lifecycle cleanup, import fail-fast, `_http_for` 503 guard, award-dup guard |
> | #22, #40, #9, #37 | ✅ **Fixed** — PR #17 (batch 2): `allSettled` fetch, getJson error classes, leaderboard-refresh logging, CSV `0o600` |
> | #14 (`favorability_score` "missing"), #14b (leaderboard `limit=100`) | ⚠️ **Over-flagged** — verified non-issues (the field is returned; there are 84 < 100 accounts) |
> | #13 (leaderboard micro-session gaming), #12 (uncosted GREEN subsidy) | 🕓 **Deferred** — scoring/economics decisions for the team (changing #13 also breaks the seed-reproduction test) |
> | #1 (CORS `*`), #2–#4 (no auth) | ⏭ **Out of scope** — production hardening; intentional for an open, synthetic-data demo |
>
> The full original report follows, unmodified.

---

# Code Review Report: GridCook Hackathon Clean-Cooking API

**Project:** GridCook Kenya Mini-Grid "Best Time to Cook" Recommender  
**Date:** 2026-07-09  
**Review Date & Time:** 2026-07-09T18:47Z  
**Scripts Reviewed:** 4 files (1,607 lines total)  
  - `data/oloika_write.py` (588 lines) — Credit ledger write path; SQLite atomic transactions  
  - `apps/api/gridcook/main.py` (895 lines) — FastAPI REST API; 40+ endpoints  
  - `mobile-app/api.js` (83 lines) — Browser client; API wiring  
  - `mobile-app/app.js` (41 lines, minified) — UI logic; time-slot selection  

**Languages:** Python 3.10+, JavaScript (vanilla)  
**Branch:** `dev-review` @ 3cb3884

**Review Team (5 Specialists):**
1. **Correctness Reviewer** — Logic errors, bugs, state corruption, transaction isolation  
2. **Reproducibility Reviewer** — Environment variables, paths, dependencies, portability  
3. **Design Reviewer** — Structure, naming, complexity, architectural choices  
4. **Security Reviewer** — CORS, authentication, authorization, injection, data leakage  
5. **Domain Reviewer** — Incentive design, credit economics, behavioral assumptions  

---

## Quality Score

| Metric | Value |
|--------|-------|
| **Overall Score** | 48/100 |
| **Verdict** | **NEEDS SIGNIFICANT WORK** — Ship blockers present |
| **Readiness** | Pre-alpha / Hackathon demo only |

---

## Deductions Summary

| Severity | Count | Typical Deduction | Total Impact |
|----------|-------|-------------------|--------------|
| **P0 (Blocker)** | 7 findings | -25 each | -175 (capped at -70) |
| **P1 (Critical)** | 15 findings | -15 each | -225 (capped at -30) |
| **P2 (Major)** | 13 findings | -10 each | -130 (capped at -15) |
| **P3 (Minor)** | 6 findings | -2 each | -12 |
| | | | **Total: -127 → 48/100** |

---

## Critical Findings (P0 — Blockers)

| # | File:Line | Issue | Confidence | Reviewers | Evidence |
|---|-----------|-------|------------|-----------|----------|
| 1 | `main.py:144` | **CORS misconfigured: `allow_origins=["*"]`** | 1.0 | Security, Design | Allows any origin to make cross-origin requests. Malicious websites can fetch user data (balances, history) and make write requests (top-up, session records) on behalf of any user. No CSRF tokens. **Fix:** Restrict to known domains, e.g. `allow_origins=['https://gridcook.example.com']` or conditional on ENV. |
| 2 | `main.py:234-278, 814, 639` | **No authentication/authorization on ANY endpoint** | 0.95 | Security | All GET/POST endpoints accept `account_id` parameter with no user identity validation. Can enumerate all users, access arbitrary wallets, record fake sessions, add credits to any account. **Fix:** Implement OAuth2/JWT token validation; derive `account_id` from authenticated session, not URL parameter. |
| 3 | `main.py:814` | **Unauthenticated POST /accounts/{account_id}/top-up — credit injection** | 0.95 | Security | Any client can add unlimited credits to any account by calling POST top-up. Combined with CORS=*, attackers can top-up arbitrary accounts from malicious websites. **Fix:** Require authentication; verify caller owns the account before allowing top-up. |
| 4 | `main.py:639` | **Unauthenticated POST /sessions — fake session injection** | 0.95 | Security | Any client can record cooking sessions on any account, triggering credit awards, leaderboard updates, ML retraining. Enables leaderboard gaming (forge sessions for top rank). **Fix:** Require authentication; verify caller owns account before recording session. |
| 5 | `oloika_write.py:205` | **Balance check runs BEFORE acquiring write lock; concurrent POSTs can overdraw** | 0.70 | Correctness | Line 205 checks `if balance - charge < 0`, but the balance was read at line 198-202 before the lock was guaranteed. Two concurrent requests can both pass the check and both reduce balance, going negative. BEGIN IMMEDIATE at line 153 should serialize (per SQLite docs), but pattern is fragile. **Fix:** Document why BEGIN IMMEDIATE prevents this, OR re-fetch balance immediately after lock is acquired. |
| 6 | `main.py:36-42` | **oloika_write import silently swallowed; module load failure invisible** | 0.90 | Correctness, Reproducibility | If oloika_write.py has syntax errors or sys.path is wrong (GRIDCOOK_DBTOOLS not set), import fails silently, oloika_write=None, and all writes are skipped. POST /sessions returns 201 (looks successful) but billing is NULL. Error is invisible. **Fix:** Fail fast at import time; raise error if critical module load fails. |
| 7 | `main.py:197, 198-202` | **Balance applied to latest month, not session month; transactions land in wrong period** | 0.85 | Correctness, Domain | `_latest_balance_month()` returns the account's most recent balance-sheet month (designed to keep wallets coherent). But if a session is recorded for June but now it's July, the charge lands on July's balance, not June's. Auditing June financials shows the session missing. **Fix:** Charge to session's calendar month, not latest month, OR document this clearly and require all sessions to be recorded in-month. |

---

## Major Findings (P1 — Critical / High-Impact)

| # | File:Line | Issue | Confidence | Category | Evidence & Fix |
|---|-----------|-------|------------|----------|----------------|
| 8 | `main.py:819-826` | **Double COMMIT in top_up() — already committed by oloika_write** | 0.95 | Correctness | oloika_write.top_up() commits at line 431 internally. main.py line 820 calls con.commit() again, violating atomicity. If exception occurs between internal commit + external commit, the external rollback won't undo already-committed ledger. **Fix:** Remove con.commit()/rollback(); oloika_write functions own their transaction boundary. |
| 9 | `main.py:800-806` | **Leaderboard refresh best-effort but masked silently; staleness undetected** | 0.80 | Correctness | award_session is called (commits), then refresh_leaderboard in separate try-catch (best-effort). If refresh fails, leaderboard is stale but user sees no indication. Repeated concurrent POSTs with refresh failures = persistent rank divergence. **Fix:** Log failures; schedule on timer instead of inline, or retry with backoff. |
| 10 | `main.py:692-699` | **Conditional billing allows sessions to bypass ledger; CSV/ledger mismatch** | 0.75 | Correctness | Line 692: `if oloika_write is not None and GRIDCOOK_DB_PATH` gates billing. If either is false, session is appended to CSV but NOT billed/awarded/on leaderboard. Ghost sessions in ML dataset. User sees nothing in app. **Fix:** Fail POST early if billing is required, or atomically write CSV+ledger together. |
| 11 | `oloika_write.py:301-307` | **Idempotency guard too strict: award_session checks cook_charge; retries fail with 409** | 0.70 | Correctness | award_session dup check includes cook_charge in the event_type filter. If client retries after network timeout, second call hits the guard and raises SessionAlreadyBilled, not idempotent. complete_session is correct (checks only cook_charge); award_session should only check reward events. **Fix:** Change line 302-305 to check only green_reward/orange_reward, not cook_charge. |
| 12 | `oloika_write.py:35-36` | **GREEN_REWARD (30 KES/kWh) is 4.75x higher than actual energy cost; uneconomic subsidy** | 0.85 | Domain | CREDITS_PER_KWH_CHARGE=25; CREDITS_PER_KES=2 → 1 kWh green cook costs 25 credits = 12.5 KES cash value, but user earns 30 credits = 15 KES value. User gains 2.4 KES per kWh green — a 20% arbitrage/subsidy with no documented funding source. Red-hour users see zero reward, cross-subsidizing green. This is an incentive but uncosted. **Fix:** Reduce GREEN_REWARD to ≤25 (break-even), OR document the subsidy level and fund it. |
| 13 | `oloika_write.py:44-45` | **Leaderboard score formula includes raw session count; incentivizes micro-sessions over consumption** | 0.90 | Domain | SCORE_SQL = '... + sessions' (raw count). User can split 1 kWh session into 24 micro-0.041-kWh sessions, earning 24 session-points instead of 1, gaming the leaderboard without changing energy or green-hour adoption. No minimum-kwh guard. **Fix:** Remove '+ sessions' term, OR add minimum kwh per session, OR normalize by energy. |
| 14 | `api.js:36, 49, 56` | **API contract mismatches: leaderboard limit=100 truncates; favorability_score not in response; byHour map has gaps** | 0.80 | Correctness | Line 35: limit=100 on leaderboard; if user not in top 100, find() returns undefined. Line 49: Map from plan.results; if hours missing, gaps default to 'red' silently. Line 56: rateFor(p.favorability_score) — field never exists in API response, always undefined. **Fix:** Use /customers endpoint for user lookup; validate all 24 hours present; use correct field (suggested_credit_gain). |
| 15 | `app.js:16, 23` | **normalizeTariff re-indexes hours by array position; scrambled input not caught; calculateTotals NaN on missing estimatedKwh** | 0.85 | Correctness | Line 16 sets hour=index, ignoring input item.hour. If API returns out-of-order tariffs, they're silently re-indexed. Line 18 checks hour===i AFTER normalizeTariff has overwritten it (check always passes). Line 23: if estimatedKwh undefined, total becomes NaN. **Fix:** Assert input item.hour===index; validate all 24 hours present before calculating totals. |
| 16 | `main.py:64-67` | **_REPO_ROOT path resolution breaks if package structure changes; CSV writes to wrong location** | 0.85 | Reproducibility | _REPO_ROOT = parents[3] assumes main.py at apps/api/gridcook/main.py. If moved or packaged differently, _REPO_ROOT is wrong, CSV writes to wrong directory, data loss across deployments. **Fix:** Require GRIDCOOK_LIVE_SESSIONS env var; no fallback to relative path. |
| 17 | `main.py:35-38, 35-42` | **GRIDCOOK_DBTOOLS and oloika_write import failure are undocumented requirements** | 0.88 | Reproducibility | sys.path modification is silent. If GRIDCOOK_DBTOOLS not set, import falls back to default path (may not exist). No error checking; oloika_write import failure is swallowed. Deployment on CI/CD will fail silently. **Fix:** Add docstring listing all required env vars. Fail fast if oloika_write import fails. |
| 18 | `main.py:71-75` | **_LIVE_SESSION_COLUMNS hardcoded; schema drift on changes** | 0.82 | Reproducibility | If cooking_sessions schema changes, columns array is not auto-updated. New fields are silently dropped from CSV. ML trainer sees incomplete schema, model diverges from reality. **Fix:** Generate columns dynamically from DB schema introspection, or add a version check/comment. |
| 19 | `main.py:53, 56-57` | **RETRAIN_EVERY (20) and RETRAIN_POLL_TIMEOUT (300) are magic numbers with no rationale** | 0.75 | Reproducibility | Default 20 sessions for retrain is undocumented. Polling timeout 300s and interval 3.0s are hardcoded. Operator can't decide if values are appropriate without understanding tradeoffs. **Fix:** Add comments explaining rationale. Make RETRAIN_POLL_INTERVAL an env var. |
| 20 | `main.py:782-793` | **_http_for relies on getattr on possibly-None oloika_write; exception mapping fails silently** | 0.85 | Design | Line 782: cls = getattr(oloika_write, name, None). If oloika_write is None (import failed), getattr returns None, isinstance check fails, exception falls through to generic 400 response. Error mapping contract is broken. **Fix:** Check 'if oloika_write is None' at start of _http_for; raise 503 immediately. |
| 21 | `mobile-app/api.js:15` | **API_BASE hardcoded to delft-api.flonat.com; no override for other deployments** | 0.85 | Reproducibility | Global window.GRIDCOOK_API_BASE is checked but not a standard deployment mechanism. Fresh clone points to hardcoded host. **Fix:** Use window.location.origin as default, falling back to global if set. Document in README. |
| 22 | `mobile-app/api.js:67-79` | **Promise.all silently swallows one error if both loadUser/loadTariffs fail; Promise.allSettled would handle both** | 0.70 | Design | If loadUser fails, loadTariffs continues in background. Only first rejection is caught. Partial data could be rendered if one succeeds and one fails. **Fix:** Use Promise.allSettled() to handle both independently. |

---

## Major Findings (P2 — Major / Design Issues)

| # | File:Line | Issue | Confidence | Category | Evidence & Fix |
|---|-----------|-------|------------|----------|----------------|
| 23 | `main.py:389-431` | **account_recommendation falls back silently to rules-based when model unavailable** | 0.78 | Design | If ml_client.account_recommendations() returns None, code uses hardcoded scoring.rank_cooking_windows() fallback without flagging degradation. Client can't distinguish model-driven from rule-based recommendations. **Fix:** Add is_fallback flag to response, or raise 503 if model required. |
| 24 | `oloika_write.py:119-265` | **complete_session is 146 lines of nested logic; hard to verify atomicity** | 0.70 | Design | Multiple INSERT/UPDATE statements in single transaction; linear structure makes rollback guarantees hard to follow. **Fix:** Add state-machine comments or pseudo-code showing operation order and rollback points. |
| 25 | `oloika_write.py:269, 172-193` | **award_session and complete_session duplicate session-upsert logic (DRY violation)** | 0.74 | Design | Both functions contain identical session INSERT/UPDATE logic. Identical SQL; only variable names differ. **Fix:** Extract into helper _upsert_session(). |
| 26 | `main.py:771-779` | **_writer function name opaque; function can raise HTTPException(503), not expected by name** | 0.75 | Design | Naming suggests connection-factory, but function raises 503 on missing DB. Callers don't expect exception from a function named _writer. **Fix:** Rename to _require_writer_or_fail(). Add docstring warning it may raise. |
| 27 | `main.py:814-826, 796-811` | **Inconsistent transaction lifecycle: top_up manually commits; award_on_ledger relies on self-commit** | 0.73 | Design | Different write endpoints manage transactions differently. Inconsistency means different failure modes per path. **Fix:** Unify: all paths self-commit (move commit into _award_on_ledger), or all managed by endpoint. |
| 28 | `main.py:239-278` | **find_customer chains 4 independent queries; inconsistent error handling if any fail** | 0.82 | Design | Separate db.query() calls for balance, charged, totals, recent. If any returns None, code silently populates with 0 or empty lists. No per-query validation. **Fix:** Unify into single SQL JOIN or VIEW to avoid partial-result bugs. |
| 29 | `oloika_write.py:471-487` | **_name_case_sql generates large CASE expression with string formatting; SQL injection risk if names contain quotes** | 0.88 | Security | Line 474: name.replace("'", "''") is a safe escape, but fragile. Better to use parameterized SQL or a view. **Fix:** Use SQL VIEW with parameterized names, or a join against a names table. |
| 30 | `api.js:73` | **loadUser lookup on leaderboard with hardcoded limit=100; doesn't work for users outside top 100** | 0.80 | Design | Line 35-36: if user not in top 100, find() returns undefined. Should use /customers endpoint instead for direct account lookup. **Fix:** Switch to /customers/{identifier}; keep leaderboard for top-N display only. |
| 31 | `main.py:102-115` | **Retrain polling loop has loose timeout; no max-iterations guard, could spin for 100+ cycles** | 0.69 | Design | While loop with only deadline check. If ml_client.retrain_status() always returns {running:true}, loop spins until timeout. No max-iterations guard. **Fix:** Add `for _ in range(MAX_RETRIES)` or max-iterations guard. Log warning if max reached. |
| 32 | `main.py:224-231` | **list_accounts accepts None filter values; silent 'match all' behavior undocumented** | 0.71 | Design | Passing account_type=None filters to None and likely matches all accounts. This is a silent contract; API doesn't document the fallback. **Fix:** Document the filter contract in endpoint docstring, or require non-None and raise 400 if missing. |
| 33 | `main.py:782` | **_http_for function name is opaque; doesn't clearly signal it maps oloika_write exceptions to HTTP** | 0.71 | Design | Name _http_for(exc) is vague. Reader won't immediately understand it's oloika_write-specific error mapping. **Fix:** Rename to _http_exception_for_oloika_write() or add module docstring with mapping table. |
| 34 | `oloika_write.py:119-130` | **complete_session function signature has 13 parameters; hard to read and error-prone** | 0.72 | Design | After keyword-only marker (*), 8 parameters. Function is doing too much (insert session, charge, award, update balance). **Fix:** Break into smaller functions or use SessionContext dataclass to group related params. |
| 35 | `oloika_write.py:471-487` | **_name_case_sql generates unbounded CASE for 12 names; consider a lookup table or view instead** | 0.68 | Design | SQL CASE statement is generated at runtime for display names. For large name lists this could balloon. **Fix:** Use a names lookup table with a JOIN instead. |

---

## Minor Findings (P3 — Minor / Polish)

| # | File:Line | Issue | Confidence |
|---|-----------|-------|------------|
| 36 | `main.py:194-196` | Health endpoint leaks account count (minor info leakage) | 0.70 |
| 37 | `main.py:128` | CSV file created with world-readable permissions (0o755); should be 0o700 | 0.68 |
| 38 | `main.py:156` | db module initialization undocumented; unclear how connection pool is set up | 0.75 |
| 39 | `mobile-app/app.js:1-41` | Minified code hides function complexity and naming quality; hard to review | 0.60 |
| 40 | `mobile-app/api.js:28-32` | getJson doesn't classify errors (network vs HTTP vs parse); all failures look the same | 0.75 |
| 41 | `mobile-app/api.js:47-64` | loadTariffs silently defaults missing hours to 'red'; should validate 24 hours present | 0.75 |

---

## Checklist Scorecard (11 Categories)

| # | Category | Result | Notes |
|---|----------|--------|-------|
| 1 | **Reproducibility** | FAIL | GRIDCOOK_DBTOOLS, GRIDCOOK_LIVE_SESSIONS, GRIDCOOK_DB_PATH undocumented; relative path fallbacks break on new machines; no requirements.txt |
| 2 | **Script Structure** | PASS | Functional architecture in oloika_write.py; modular endpoints in main.py; api.js/app.js are structured but app.js is minified |
| 3 | **Output Hygiene** | PASS | Return formats documented; formatCredit vs formatKes distinction clear |
| 4 | **Function Quality** | PASS | Functions have docstrings; clear contracts (though some functions oversized) |
| 5 | **Domain Correctness** | FAIL | Leaderboard score formula incentivizes micro-sessions; GREEN_REWARD subsidy uncosted; suggested_credit_gain rounding direction not specified |
| 6 | **Figure Quality** | N/A | No figures; API returns JSON/CSV |
| 7 | **Data Persistence** | FAIL | Transaction isolation assumed but not verified; leaderboard refresh can diverge from ledger; CSV/ledger mismatch on conditional billing |
| 8 | **Dependencies** | FAIL | No requirements.txt; no version pinning; oloika_write import swallowed on failure |
| 9 | **Python-Specific** | PASS | Type hints partial; exception hierarchy present; f-strings used; isolation_level=None correct for WAL |
| 10 | **R-Specific** | N/A | N/A |
| 11 | **Cross-Language Verification** | FAIL | API contract mismatches (favorability_score not in response; leaderboard limit=100 truncates users; app.js re-indexes hours) |

**Checklist Summary: 3/11 Pass** (plus 2 N/A)

---

## Residual Risks (Cannot Be Verified from Code Alone)

1. **SQLite WAL + BEGIN IMMEDIATE isolation** — The code assumes WAL mode with IMMEDIATE transactions prevents concurrent balance overwrites. This is correct per SQLite docs, but if PRAGMA settings are disabled at runtime or WAL is not available, balance corruption is possible.

2. **ML model inference accuracy** — The suggested_credit_gain is output by an "nn-v5" model (neural network). No specification of model architecture, training data, or performance metrics. If model is stale or poorly calibrated, recommendations will be poor.

3. **Leaderboard staleness acceptable** — Leaderboard is rebuilt asynchronously. A user's rank may diverge from canonical billing_ledger for minutes. The code accepts this (design note line 12-13), but users may not understand why their rank changes after a session.

4. **Month-keying wallet stability** — Wallets are pinned to seeded June 2025 month. If the system runs into July, all transactions apply to June wallet. Users will not understand this; support load will increase.

5. **Credit redemption path undefined** — Users earn integer credits on a ledger. The UI displays creditKes and shows them as KES (currency). But there's no endpoint to exchange credits back for cash or energy discount. Users may hoard credits or abandon the app if redemption is unclear.

6. **Capacity adjustment determinism** — capacity.adjust_windows() can downgrade slot_color. If this logic is non-deterministic or depends on real-time load, two identical session records at different times will have different rewards (one green=30, one orange=8). Audit will be impossible; users will feel cheated.

7. **No load-testing or concurrency stress** — The code uses BEGIN IMMEDIATE and assumes proper SQLite WAL behavior. But no load-test output shown. Under 100 concurrent users, connection pooling, lock contention, or pragma-per-connection overhead may cause timeouts or silently dropped transactions.

---

## Priority Fixes (in order of impact)

1. **[BLOCKER] Implement authentication and authorization** — All GET/POST endpoints must validate user identity and ownership before allowing access. Currently, any attacker can dump all user data and manipulate any account.

2. **[BLOCKER] Restrict CORS to known origins** — Set allow_origins to specific domain(s) and environment-specific fallback, not `["*"]`.

3. **[BLOCKER] Fail fast on oloika_write import failure** — Either guarantee the import succeeds (set GRIDCOOK_DBTOOLS correctly) or raise an error at startup, never silently disable billing.

4. **[CRITICAL] Fix leaderboard score formula** — Remove or gate the `+ sessions` term to prevent micro-session gaming. Gaming undermines the incentive (shift cooking to green hours).

5. **[CRITICAL] Fix API contract mismatches** — api.js uses undefined fields (favorability_score), assumes 100-account leaderboard, re-indexes hours. main.py needs to return correct response schema.

6. **[CRITICAL] Document and validate environment variables** — Create requirements.txt, add docstring listing all required GRIDCOOK_* vars, fail fast if any are missing or invalid.

7. **[CRITICAL] Audit transaction isolation** — Verify that BEGIN IMMEDIATE actually prevents concurrent balance overwrites. Test under load (100+ concurrent POSTs) to confirm WAL isolation works.

8. **[MAJOR] Unify transaction lifecycle** — All write endpoints should use consistent transaction management (either self-committing or endpoint-managed, not mixed).

9. **[MAJOR] Fix rounding semantics for suggested_credit_gain** — Show users the integer credits they will *receive*, not the fractional model estimate. Use floor() for transparency.

10. **[MAJOR] De-minify app.js** — Preserve source code for future audits; minification obscures complexity and potential bugs.

---

## Positive Observations

- **Atomic transaction design** — The use of BEGIN IMMEDIATE, explicit COMMIT/ROLLBACK, and transaction-scoped operations is sound. The ledger design is correct for preventing double-charging (outside concurrency edge cases).

- **Error hierarchy** — WriteError, InsufficientCredits, SessionAlreadyBilled exceptions are well-defined and appropriately raised.

- **Pydantic validation** — FastAPI routes use Pydantic models for input validation, catching malformed requests early.

- **Parameterized SQL** — oloika_write.py consistently uses ? bindings; no obvious SQL injection vectors.

- **Graceful fallback in UI** — api.js has try-catch to fall back to mock data on network failure; UX degrades gracefully.

- **Idempotency consideration** — SessionAlreadyBilled guard is an attempt at idempotent retries (though slightly over-strict on award_session).

- **Deterministic display names** — Leaderboard display names are derived from account IDs deterministically; same account always shows same name across sessions.

---

## Recommendations for Improvement

### Before Production

- **Mandatory:** Implement OAuth2 / JWT authentication on all endpoints.
- **Mandatory:** Restrict CORS to known domains only.
- **Mandatory:** Create requirements.txt with pinned versions.
- **Mandatory:** Document all GRIDCOOK_* environment variables in a README and fail fast if missing.
- **Mandatory:** Audit transaction isolation under realistic load (100+ concurrent users).
- **Mandatory:** Fix leaderboard score formula to prevent micro-session gaming.
- **Mandatory:** Fix API response schema (remove undefined fields, validate all 24 hours in tariffs).

### Before Next Iteration

- Unify transaction lifecycle across write endpoints.
- De-minify app.js and add source map.
- Add logging for critical paths (ledger commits, leaderboard refreshes, retrain triggers).
- Implement rate-limiting on endpoints to prevent enumeration/flooding attacks.
- Add integration tests for concurrent session recording (verify balance isolation).
- Document credit redemption path and wallet month-keying in UI.

### Longer Term

- Run A/B tests on reward ratios (GREEN=30 vs alternatives) to verify behavioral response.
- Implement certificate pinning in mobile app for HTTPS security.
- Add telemetry to measure green-window adoption rate and session concentration.
- Build audit trails (immutable log of all ledger operations) for financial transparency.

---

## Conclusion

The GridCook hackathon code demonstrates a solid understanding of atomic transactions, API design, and incentive mechanics. However, **the system is not ready for production deployment** due to critical security gaps (no authentication), correctness issues (transaction isolation edge cases, leaderboard divergence), and domain design problems (leaderboard gaming, uncosted subsidy). 

**For a hackathon demo, the code is functional.** The core credit ledger is sound, and the mobile UI is usable. But before even a beta deployment to real users, authentication, CORS restriction, environment documentation, and transaction-concurrency verification are **mandatory non-negotiables.**

The team has built something that *works* for a controlled demo. The next phase must focus on **security and robustness** before expanding the user base.

---

## Appendix: Deduplication Notes

**Cross-reviewer agreements (findings confirmed by multiple specialists):**

- **CORS=*** (Security + Design): Identified by both security-reviewer (P0 auth breach) and design-reviewer (P1 architectural risk).
- **Missing authentication** (Security, primary reviewer): Identified only by security; flagged by correctness as implicit in authorization bypass findings.
- **oloika_write import failure** (Correctness + Reproducibility): Identified by both correctness-reviewer (silent billing skip) and reproducibility-reviewer (deployment failure).
- **Leaderboard score gaming** (Domain + Correctness): Identified by domain-reviewer (perverse incentive) and correctness-reviewer (state mismatch from duplicate sessions).
- **API contract mismatches** (Correctness + Design): Identified by correctness-reviewer (field undefined) and design-reviewer (missing validation).

**All cross-reviewer agreements consolidated with highest severity + highest confidence + union of evidence.**

---

**Report Generated:** 2026-07-09T18:47Z  
**Session ID:** code-review / dev-rebuild  
**Next Steps:** Address P0 findings before any user-facing deployment.
