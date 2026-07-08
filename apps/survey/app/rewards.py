"""Electricity-credit rewards (Section 3 of the design).

Completing a session earns survey.reward_kwh, doubled for arm C. The reward
SMS doubles as the load-shifting nudge, and its wording depends on the
respondent's credit-window arm: A and C credits are valid only 10am-3pm,
arm B (control) credits are valid anytime. Respondents not yet randomised
get the daytime wording, matching what S2 told them at enrolment.

Credits are recorded as pending Reward rows; actual delivery happens in the
utility's vending system (export with `survey rewards export`).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .config import get_settings
from .gateways.base import SmsGateway
from .models import Reward, SurveySession

logger = logging.getLogger(__name__)

# [X]/[day] placeholders from SYS_REWARD, resolved per arm.
REWARD_STRINGS = {
    "en": {
        "daytime": "Asante! You earned {x} FREE units valid tomorrow 10am-3pm (saa 4 asubuhi-saa 9 alasiri). Try cooking lunch on your EPC or hob!",
        "anytime": "Asante! You earned {x} FREE units valid any time tomorrow.",
        "streak": "Bonus! You completed {n} surveys in a row and earned an extra {x} FREE units. Asante sana!",
    },
    "sw": {
        "daytime": "Asante! Umepata units {x} za BURE zinazotumika kesho 10am-3pm (saa 4 asubuhi-saa 9 alasiri). Jaribu kupika chakula cha mchana kwa EPC au jiko lako!",
        "anytime": "Asante! Umepata units {x} za BURE zinazotumika kesho wakati wowote.",
        "streak": "Bonasi! Umejibu tafiti {n} mfululizo na kupata units {x} za ziada za BURE. Asante sana!",
    },
}


def _reward_text(lang: str, key: str, **kwargs) -> str:
    table = REWARD_STRINGS.get(lang, REWARD_STRINGS["en"])
    return table[key].format(**kwargs)


def _fmt(kwh: float) -> str:
    return f"{kwh:g}"


def on_session_completed(db: Session, session: SurveySession, gateway: SmsGateway) -> list[str]:
    """Record credits and send the reward/thanks message. Returns bodies sent."""
    from .engine import _send  # deferred: engine imports this module

    settings = get_settings()
    survey = session.survey
    respondent = session.respondent
    lang = respondent.language
    sent: list[str] = []

    if survey.reward_kwh > 0:
        kwh = survey.reward_kwh * (2 if respondent.arm == "C" else 1)
        db.add(
            Reward(
                respondent_id=respondent.id,
                session_id=session.id,
                kwh=kwh,
                kind="completion",
            )
        )
        window = "anytime" if respondent.arm == "B" else "daytime"
        sent.append(_send(db, gateway, respondent.phone, _reward_text(lang, window, x=_fmt(kwh))))
    elif survey.thanks_text:
        sent.append(_send(db, gateway, respondent.phone, survey.thanks_text))

    # Streak bookkeeping (weekly/monthly cycle only, per the schedule rules).
    if survey.module in ("weekly", "monthly", "quarterly"):
        respondent.completion_streak += 1
        respondent.missed_weekly_streak = 0
        respondent.rested = False
        if respondent.completion_streak >= settings.streak_length:
            respondent.completion_streak = 0
            bonus = settings.streak_bonus_kwh * (2 if respondent.arm == "C" else 1)
            db.add(
                Reward(
                    respondent_id=respondent.id,
                    session_id=session.id,
                    kwh=bonus,
                    kind="streak_bonus",
                )
            )
            sent.append(
                _send(
                    db,
                    gateway,
                    respondent.phone,
                    _reward_text(lang, "streak", n=settings.streak_length, x=_fmt(bonus)),
                )
            )
    return sent
