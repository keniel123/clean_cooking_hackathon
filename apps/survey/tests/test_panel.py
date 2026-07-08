"""Panel calendar and operating rules (Section 4 + Schedule & rotation)."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.engine import handle_inbound, set_variable
from app.models import Respondent, Survey, SurveySession
from app.panel import assign_arms, due_survey_slug, load_panel_plan, run_panel
from app.survey_loader import load_survey_directory

from tests.conftest import SURVEYS_DIR

EAT = ZoneInfo("Africa/Nairobi")
CONSENT_DT = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)  # Monday = panel day 0
PHONE = "+254712345678"


@pytest.fixture()
def panel(db):
    load_survey_directory(db, SURVEYS_DIR)
    plan = load_panel_plan(SURVEYS_DIR / "panel.yaml")
    surveys = {s.slug: s for s in db.scalars(select(Survey))}
    return plan, surveys


def _respondent(db, consented=True, **kwargs):
    r = Respondent(phone=kwargs.pop("phone", PHONE), language="en", **kwargs)
    if consented:
        r.consented_at = CONSENT_DT
    db.add(r)
    db.commit()
    return r


def _mk_session(db, survey, respondent, started, status="completed"):
    s = SurveySession(
        survey_id=survey.id, respondent_id=respondent.id, status=status, started_at=started
    )
    db.add(s)
    db.commit()
    return s


def _utc(y, m, d, hh=9):
    return datetime(y, m, d, hh, tzinfo=timezone.utc)


def test_panel_calendar_progression(db, panel):
    plan, surveys = panel
    r = _respondent(db)
    due = lambda d: due_survey_slug(db, r, plan, d)  # noqa: E731

    assert due(date(2026, 1, 5)) == "ecooking-enrolment"
    _mk_session(db, surveys["ecooking-enrolment"], r, _utc(2026, 1, 5))
    assert due(date(2026, 1, 5)) is None  # one session per day

    assert due(date(2026, 1, 6)) == "ecooking-baseline-1"  # day 1
    _mk_session(db, surveys["ecooking-baseline-1"], r, _utc(2026, 1, 6))
    assert due(date(2026, 1, 7)) is None  # baseline 2 waits until day 3
    assert due(date(2026, 1, 8)) == "ecooking-baseline-2"
    _mk_session(db, surveys["ecooking-baseline-2"], r, _utc(2026, 1, 8))
    assert due(date(2026, 1, 10)) == "ecooking-baseline-3"  # day 5
    _mk_session(db, surveys["ecooking-baseline-3"], r, _utc(2026, 1, 10))

    assert due(date(2026, 1, 11)) is None  # week 0 has no pulse
    assert due(date(2026, 1, 12)) == "ecooking-pulse-week-1"  # day 7, week 1
    _mk_session(db, surveys["ecooking-pulse-week-1"], r, _utc(2026, 1, 12))
    assert due(date(2026, 1, 13)) is None  # already surveyed this week

    assert due(date(2026, 1, 19)) == "ecooking-pulse-week-2"
    assert due(date(2026, 1, 26)) == "ecooking-pulse-week-3"
    assert due(date(2026, 2, 2)) == "ecooking-monthly-a"  # week 4 -> monthly (odd month)
    assert due(date(2026, 2, 9)) == "ecooking-pulse-week-1"  # month 2 rotation restarts
    assert due(date(2026, 3, 2)) == "ecooking-monthly-b"  # month 2 week 4 (even month)
    assert due(date(2026, 3, 30)) == "ecooking-quarterly"  # month 3 week 4
    assert due(date(2026, 11, 30)) == "ecooking-rebaseline"  # month 12 week 3 (day 329)
    assert due(date(2026, 12, 7)) == "ecooking-quarterly"  # month 12 week 4

    _mk_session(db, surveys["ecooking-rebaseline"], r, _utc(2026, 11, 30))
    assert due(date(2027, 11, 29)) is None or due(date(2027, 11, 29)) != "ecooking-rebaseline"


def test_rested_respondent_skips_pulse_but_keeps_monthly(db, panel):
    plan, surveys = panel
    r = _respondent(db, rested=True)
    for slug, day in [("ecooking-enrolment", 5), ("ecooking-baseline-1", 6),
                      ("ecooking-baseline-2", 8), ("ecooking-baseline-3", 10)]:
        _mk_session(db, surveys[slug], r, _utc(2026, 1, day))
    assert due_survey_slug(db, r, plan, date(2026, 1, 12)) is None  # pulse suppressed
    assert due_survey_slug(db, r, plan, date(2026, 2, 2)) == "ecooking-monthly-a"


def test_run_panel_dispatch_remind_expire(db, panel, gateway):
    plan, _ = panel
    _respondent(db, consented=False)
    now = datetime(2026, 1, 5, 19, 0, tzinfo=EAT)  # Monday evening

    counts = run_panel(db, gateway, plan=plan, now=now)
    assert counts["dispatched"] == 1  # enrolment invitation
    assert "Habari" in gateway.sent[-1][1]

    counts = run_panel(db, gateway, plan=plan, now=now + timedelta(hours=25))
    assert counts == {"expired": 0, "reminded": 1, "rested": 0, "dispatched": 0}
    assert "waiting" in gateway.sent[-1][1]  # SYS_REMIND

    counts = run_panel(db, gateway, plan=plan, now=now + timedelta(hours=49))
    assert counts["expired"] == 1
    assert counts["reminded"] == 0  # only one reminder, ever


def test_no_dispatch_on_sundays(db, panel, gateway):
    plan, _ = panel
    _respondent(db, consented=False)
    sunday = datetime(2026, 1, 4, 19, 0, tzinfo=EAT)
    counts = run_panel(db, gateway, plan=plan, now=sunday)
    assert counts["dispatched"] == 0
    assert gateway.sent == []


def test_slot_filter(db, panel, gateway):
    plan, _ = panel
    _respondent(db, consented=False)  # no B24 answer yet -> defaults to evening
    now = datetime(2026, 1, 5, 7, 0, tzinfo=EAT)
    assert run_panel(db, gateway, plan=plan, now=now, slot="morning")["dispatched"] == 0
    assert run_panel(db, gateway, plan=plan, now=now, slot="evening")["dispatched"] == 1


def test_three_missed_pulses_rest_the_respondent(db, panel, gateway):
    plan, surveys = panel
    r = _respondent(db)
    set_variable(db, r.id, "own_epc", "3")
    set_variable(db, r.id, "own_hob", "3")
    for slug, day in [("ecooking-enrolment", 5), ("ecooking-baseline-1", 6),
                      ("ecooking-baseline-2", 8), ("ecooking-baseline-3", 10)]:
        _mk_session(db, surveys[slug], r, _utc(2026, 1, day))

    # Three weekly pulses dispatched and ignored (each expires after 48h).
    for monday in (12, 19, 26):
        counts = run_panel(db, gateway, plan=plan, now=datetime(2026, 1, monday, 19, 0, tzinfo=EAT))
        assert counts["dispatched"] == 1
        run_panel(db, gateway, plan=plan, now=datetime(2026, 1, monday + 2, 20, 0, tzinfo=EAT))

    db.refresh(r)
    assert r.missed_weekly_streak == 3
    assert r.rested is True
    assert "fewer questions" in gateway.sent[-1][1]  # re-engagement message

    # Week 4: the monthly module still goes out...
    counts = run_panel(db, gateway, plan=plan, now=datetime(2026, 2, 2, 19, 0, tzinfo=EAT))
    assert counts["dispatched"] == 1
    # ...and completing it un-rests the household.
    for reply in ["1", "1", "1", "1", "1", "1"]:  # M1-M4, M6a, M7 (M5 skipped: no EPC)
        handle_inbound(db, PHONE, reply, gateway)
    db.refresh(r)
    assert r.rested is False
    assert r.completion_streak == 1


def test_assign_arms_stratified_40_40_20(db, panel):
    plan, surveys = panel
    for i in range(10):
        r = _respondent(db, phone=f"+2547000000{i:02d}", site="Kisii")
        set_variable(db, r.id, "own_epc", "1" if i < 5 else "3")
    db.commit()
    unconsented = _respondent(db, phone="+254799999999", consented=False)

    counts = assign_arms(db, seed=42)
    # two strata of 5 -> each gets 2 A, 2 B, 1 C
    assert (counts["A"], counts["B"], counts["C"], counts["strata"]) == (4, 4, 2, 2)
    db.refresh(unconsented)
    assert unconsented.arm is None  # randomise consented households only
