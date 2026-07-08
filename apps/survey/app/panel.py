"""Panel scheduler (Sections 2.4 and 4 of the design, plus the operating
rules from the Schedule & rotation sheet).

The panel calendar for each household is anchored to its consent date (day 0):

  day 0        enrolment (language, consent, respondent check)
  days 1/3/5   baseline sessions 1-3
  weekly       week w starts on day 7*w; weeks 1-3 of each 4-week month get a
               pulse variant (rotation repeats every 4 weeks), week 4 gets the
               monthly module (M6a/M5 in odd months, M6b/M8 in even months)
  months 3/6/9/12  quarterly module replaces that month's monthly
  month 12     re-baseline replaces the week-3 pulse

Operating rules implemented by run_panel():
  - send at the household's preferred time slot (B24), default evening
  - at most one session per respondent per day; none on Sundays
  - 48h response window; one SYS_REMIND at 24h
  - 3 consecutive missed weekly surveys -> rest from the pulse (monthly
    continues); any completed session un-rests (handled in rewards.py)

run_panel() is idempotent within a day — run it from cron once per slot:
  0 7,12,19 * * *  survey panel run --slot <morning|midday|evening>
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .engine import _send, load_variables, start_survey
from .gateways.base import SmsGateway
from .models import (
    SESSION_ACTIVE,
    SESSION_EXPIRED,
    Respondent,
    RespondentVariable,
    Survey,
    SurveySession,
)

logger = logging.getLogger(__name__)

RESPONSE_WINDOW_HOURS = 48
REMINDER_AFTER_HOURS = 24
MISSED_WEEKLY_LIMIT = 3
QUARTERLY_MONTHS = (3, 6, 9, 12)

# SYS_REMIND from the question bank, plus the re-engagement message.
PANEL_STRINGS = {
    "en": {
        "remind": "Yesterday's questions are waiting. Reply now to earn your free units!",
        "reengage": "We miss your answers! We will send fewer questions for now. Reply to your next survey to keep earning free units.",
    },
    "sw": {
        "remind": "Maswali ya jana yanakusubiri. Jibu sasa upate units zako za bure!",
        "reengage": "Tunakukumbuka! Kwa sasa tutatuma maswali machache. Jibu utafiti wako ujao kuendelea kupata units za bure.",
    },
}


def _pt(lang: str, key: str) -> str:
    return PANEL_STRINGS.get(lang, PANEL_STRINGS["en"])[key]


@dataclass
class PanelPlan:
    enrolment: str
    baseline: list[dict]  # [{"slug": ..., "day": ...}] in order
    weekly: list[str]  # pulse variants for weeks 1-3 of each 4-week month
    monthly: list[str]  # alternated by month parity: odd months [0], even [1]
    quarterly: str
    rebaseline: str
    rebaseline_month: int = 12
    slugs: list[str] = field(default_factory=list)


def load_panel_plan(path: str | Path = "surveys/panel.yaml") -> PanelPlan:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    plan = PanelPlan(
        enrolment=data["enrolment"],
        baseline=data["baseline"],
        weekly=data["weekly"],
        monthly=data["monthly"],
        quarterly=data["quarterly"],
        rebaseline=data["rebaseline"]["slug"],
        rebaseline_month=data["rebaseline"].get("month", 12),
    )
    plan.slugs = (
        [plan.enrolment]
        + [b["slug"] for b in plan.baseline]
        + plan.weekly
        + plan.monthly
        + [plan.quarterly, plan.rebaseline]
    )
    return plan


def _local_now(now: datetime | None) -> datetime:
    return now or datetime.now(ZoneInfo(get_settings().timezone))


def due_survey_slug(
    db: Session, respondent: Respondent, plan: PanelPlan, today: date
) -> str | None:
    """Which session (if any) this respondent should receive today."""
    sessions = db.scalars(
        select(SurveySession).where(SurveySession.respondent_id == respondent.id)
    ).all()
    by_slug: dict[str, list[SurveySession]] = {}
    for s in sessions:
        by_slug.setdefault(s.survey.slug, []).append(s)
        if s.started_at.date() == today:
            return None  # never more than one session per day
        if s.status == SESSION_ACTIVE:
            return None  # finish (or expire) the open session first

    if plan.enrolment not in by_slug:
        return plan.enrolment
    if respondent.consented_at is None:
        return None  # enrolment sent but consent not (yet) given

    day = (today - respondent.consented_at.date()).days
    for entry in plan.baseline:
        if entry["slug"] not in by_slug:
            return entry["slug"] if day >= entry["day"] else None

    week = day // 7  # week 1 starts on day 7
    if week < 1:
        return None
    month = (week - 1) // 4 + 1
    week_of_month = (week - 1) % 4 + 1
    week_start = respondent.consented_at.date() + timedelta(days=7 * week)

    if month == plan.rebaseline_month and week_of_month == 3:
        slug = plan.rebaseline
        if by_slug.get(slug):  # re-baseline happens once, ever
            return None
        return slug

    if week_of_month <= 3:
        if respondent.rested:
            return None
        slug = plan.weekly[week_of_month - 1]
    elif month in QUARTERLY_MONTHS:
        slug = plan.quarterly
    else:
        slug = plan.monthly[(month - 1) % len(plan.monthly)]

    # Weekly/monthly slugs recur — only dispatch once per calendar slot.
    for s in by_slug.get(slug, []):
        if s.started_at.date() >= week_start:
            return None
    return slug


def _expire_and_remind(
    db: Session, gateway: SmsGateway, now: datetime, send_reminders: bool
) -> dict:
    counts = {"expired": 0, "reminded": 0, "rested": 0}
    active = db.scalars(
        select(SurveySession).where(SurveySession.status == SESSION_ACTIVE)
    ).all()
    for session in active:
        respondent = session.respondent
        # SQLite round-trips timestamps as naive UTC; compare in UTC.
        started = session.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age_hours = (now.astimezone(timezone.utc) - started).total_seconds() / 3600
        if age_hours >= RESPONSE_WINDOW_HOURS:
            session.status = SESSION_EXPIRED
            counts["expired"] += 1
            respondent.completion_streak = 0
            if session.survey.module == "weekly":
                respondent.missed_weekly_streak += 1
                if respondent.missed_weekly_streak >= MISSED_WEEKLY_LIMIT and not respondent.rested:
                    respondent.rested = True
                    counts["rested"] += 1
                    _send(db, gateway, respondent.phone, _pt(respondent.language, "reengage"))
        elif (
            send_reminders
            and age_hours >= REMINDER_AFTER_HOURS
            and session.reminded_at is None
        ):
            session.reminded_at = now
            counts["reminded"] += 1
            _send(db, gateway, respondent.phone, _pt(respondent.language, "remind"))
    db.commit()
    return counts


def run_panel(
    db: Session,
    gateway: SmsGateway,
    plan: PanelPlan | None = None,
    now: datetime | None = None,
    slot: str | None = None,
) -> dict:
    """One scheduler pass: expire stale sessions, send reminders, dispatch
    whatever is due. Sundays get expiry only (never send on Sundays)."""
    plan = plan or load_panel_plan()
    now = _local_now(now)
    today = now.date()
    is_sunday = today.weekday() == 6

    counts = _expire_and_remind(db, gateway, now, send_reminders=not is_sunday)
    counts["dispatched"] = 0
    if is_sunday:
        return counts

    surveys = {
        s.slug: s for s in db.scalars(select(Survey).where(Survey.slug.in_(plan.slugs)))
    }
    missing = [slug for slug in plan.slugs if slug not in surveys]
    if missing:
        raise ValueError(
            f"Panel surveys not loaded: {', '.join(missing)}. Run: survey panel load"
        )

    respondents = db.scalars(
        select(Respondent).where(Respondent.opted_out == False)  # noqa: E712
    ).all()
    for respondent in respondents:
        if slot and (respondent.preferred_send_time or "evening") != slot:
            continue
        slug = due_survey_slug(db, respondent, plan, today)
        if slug and start_survey(
            db, surveys[slug], respondent, gateway, resend=True,
            now=now.astimezone(timezone.utc),
        ):
            counts["dispatched"] += 1
    db.commit()
    return counts


def assign_arms(db: Session, seed: int | None = None) -> dict:
    """Randomise credit-window arms A/B/C (40/40/20) for consented respondents
    without one, stratified by village and EPC ownership (B7)."""
    rng = random.Random(seed)
    pending = db.scalars(
        select(Respondent).where(
            Respondent.arm.is_(None),
            Respondent.consented_at.is_not(None),
            Respondent.opted_out == False,  # noqa: E712
        )
    ).all()

    strata: dict[tuple, list[Respondent]] = {}
    for respondent in pending:
        own_epc = db.scalar(
            select(RespondentVariable.value).where(
                RespondentVariable.respondent_id == respondent.id,
                RespondentVariable.var == "own_epc",
            )
        )
        key = (respondent.site or "", own_epc or str(respondent.meta.get("epc", "?")))
        strata.setdefault(key, []).append(respondent)

    counts = {"A": 0, "B": 0, "C": 0}
    pattern = ["A", "A", "B", "B", "C"]  # 40/40/20
    for group in strata.values():
        allocation = (pattern * (len(group) // len(pattern) + 1))[: len(group)]
        rng.shuffle(allocation)
        rng.shuffle(group)
        for respondent, arm in zip(group, allocation):
            respondent.arm = arm
            counts[arm] += 1
    db.commit()
    counts["strata"] = len(strata)
    return counts
