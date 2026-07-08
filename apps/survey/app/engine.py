"""Survey state machine.

Each respondent has at most one active SurveySession. Question texts are sent
verbatim in the respondent's language (chosen at enrolment via S0). Every
answer is stored twice: as an Answer row (full history) and as the current
value of its variable in RespondentVariable, which is what ask_if/skip_if
conditions evaluate against — including conditions on answers from earlier
sessions (e.g. skip W4-W7 if baseline said no EPC and no hob).

Invalid replies follow the operating rule from the question bank: send
SYS_INVALID once, then accept the next reply as given (stored raw with
is_valid=False) so sessions never get stuck.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .gateways.base import SmsGateway
from .models import (
    SESSION_ACTIVE,
    SESSION_COMPLETED,
    SESSION_EXPIRED,
    SESSION_OPTED_OUT,
    Answer,
    MessageLog,
    Question,
    Respondent,
    RespondentVariable,
    Survey,
    SurveySession,
    utcnow,
)
from .phone import PhoneError, normalize_phone

logger = logging.getLogger(__name__)

OPT_OUT_KEYWORDS = {"stop", "end", "unsubscribe", "acha"}

YES_WORDS = {"yes", "y", "yeah", "ndiyo", "ndio"}
NO_WORDS = {"no", "n", "hapana"}

# System texts from the question bank (SYS_INVALID, SYS_OPTOUT) plus fixed strings.
STRINGS = {
    "en": {
        "invalid": "Sorry, we did not understand. Please reply with the number of your answer, e.g. 2",
        "opted_out": "You have left the survey. No more questions will be sent. Thank you!",
    },
    "sw": {
        "invalid": "Samahani, hatukuelewa. Tafadhali jibu kwa namba ya jibu lako, mfano 2",
        "opted_out": "Umeondoka kwenye utafiti. Hutatumiwa maswali tena. Asante!",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    table = STRINGS.get(lang, STRINGS["en"])
    return table[key].format(**kwargs)


def localized(texts: dict | None, lang: str) -> str:
    """Pick the language variant, falling back to English then to anything."""
    texts = texts or {}
    body = texts.get(lang) or texts.get("en") or next(iter(texts.values()), "")
    return body.replace("{utility}", get_settings().utility_name)


def render_question(question: Question, lang: str) -> str:
    return localized(question.texts, lang)


def validate_answer(question: Question, text: str) -> tuple[str | None, bool]:
    """Return (normalized_value, ok). Values are stored as numeric codes
    (the codebook maps codes to labels), never as option labels."""
    cleaned = text.strip()
    if question.qtype == "single":
        if cleaned.isdigit() and 1 <= int(cleaned) <= (question.choices or 0):
            return str(int(cleaned)), True
        return None, False
    if question.qtype == "multi":
        tokens = [tok for tok in re.split(r"[,\s;]+", cleaned) if tok]
        if not tokens or not all(tok.isdigit() for tok in tokens):
            return None, False
        values = sorted({int(tok) for tok in tokens})
        if not all(1 <= v <= (question.choices or 0) for v in values):
            return None, False
        return ",".join(str(v) for v in values), True
    if question.qtype == "number":
        try:
            value = float(cleaned.replace(",", ""))
        except ValueError:
            return None, False
        if question.min_value is not None and value < question.min_value:
            return None, False
        if question.max_value is not None and value > question.max_value:
            return None, False
        return (str(int(value)) if value.is_integer() else str(value)), True
    if question.qtype == "yesno":
        word = cleaned.lower().rstrip(".!")
        if word in YES_WORDS:
            return "yes", True
        if word in NO_WORDS:
            return "no", True
        return None, False
    # text
    return (cleaned, True) if cleaned else (None, False)


def _send(db: Session, gateway: SmsGateway, phone: str, body: str) -> str:
    result = gateway.send(phone, body)
    db.add(
        MessageLog(
            phone=phone,
            direction="out",
            body=body,
            provider=result.provider,
            provider_message_id=result.message_id,
            status=result.status,
        )
    )
    return body


def load_variables(db: Session, respondent_id: int) -> dict[str, str]:
    rows = db.scalars(
        select(RespondentVariable).where(RespondentVariable.respondent_id == respondent_id)
    )
    return {row.var: row.value for row in rows}


def set_variable(db: Session, respondent_id: int, var: str, value: str) -> None:
    row = db.scalar(
        select(RespondentVariable).where(
            RespondentVariable.respondent_id == respondent_id,
            RespondentVariable.var == var,
        )
    )
    if row is None:
        db.add(RespondentVariable(respondent_id=respondent_id, var=var, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    db.flush()  # conditions re-query variables before this transaction commits


def _condition_matches(cond: dict, variables: dict[str, str]) -> bool:
    value = variables.get(cond.get("var", ""))
    if value is None:
        return False  # unknown variable: condition is simply not met
    if "equals" in cond:
        return str(value) == str(cond["equals"])
    if "not_equals" in cond:
        return str(value) != str(cond["not_equals"])
    if "in" in cond:
        return str(value) in {str(v) for v in cond["in"]}
    if "contains" in cond:  # multi-select answers, e.g. "1,4" contains 4
        return str(cond["contains"]) in str(value).split(",")
    return False


def step_is_asked(question: Question, variables: dict[str, str]) -> bool:
    if question.ask_if and not all(_condition_matches(c, variables) for c in question.ask_if):
        return False
    if question.skip_if and all(_condition_matches(c, variables) for c in question.skip_if):
        return False
    return True


def _apply_sets(db: Session, respondent: Respondent, question: Question, value: str) -> None:
    spec = question.sets or {}
    attr = spec.get("attr")
    if not attr:
        return
    mapped = (spec.get("map") or {}).get(str(value), value)
    if attr == "language":
        respondent.language = mapped
    elif attr == "preferred_send_time":
        respondent.preferred_send_time = mapped
    elif attr == "consent":
        if value == "yes":
            respondent.consented_at = utcnow()
    else:
        logger.warning("Question %s sets unknown attribute %r", question.key, attr)


def _advance(
    db: Session, session: SurveySession, gateway: SmsGateway, from_position: int
) -> list[str]:
    """Move to the next askable question after from_position, sending any
    system messages passed along the way. Completes the session (and grants
    the reward) when no questions remain."""
    respondent = session.respondent
    lang = respondent.language
    variables = load_variables(db, respondent.id)
    sent: list[str] = []

    for question in sorted(session.survey.questions, key=lambda q: q.position):
        if question.position <= from_position:
            continue
        if not step_is_asked(question, variables):
            continue
        if question.qtype == "system":
            sent.append(_send(db, gateway, respondent.phone, render_question(question, lang)))
            continue
        session.current_position = question.position
        session.invalid_count = 0
        sent.append(_send(db, gateway, respondent.phone, render_question(question, lang)))
        return sent

    session.status = SESSION_COMPLETED
    session.completed_at = utcnow()
    from .rewards import on_session_completed

    sent.extend(on_session_completed(db, session, gateway))
    return sent


def start_survey(
    db: Session,
    survey: Survey,
    respondent: Respondent,
    gateway: SmsGateway,
    resend: bool = False,
    now: datetime | None = None,
) -> list[str]:
    """Open a session and send the first question. Returns bodies sent
    (empty if the respondent was skipped)."""
    if respondent.opted_out:
        return []
    if not survey.questions:
        raise ValueError(f"Survey {survey.slug!r} has no questions")

    active = db.scalar(
        select(SurveySession).where(
            SurveySession.respondent_id == respondent.id,
            SurveySession.status == SESSION_ACTIVE,
        )
    )
    if active:  # never run two surveys at once — inbound routing would be ambiguous
        return []
    previous = db.scalar(
        select(SurveySession).where(
            SurveySession.respondent_id == respondent.id,
            SurveySession.survey_id == survey.id,
        )
    )
    if previous and not resend:
        return []

    now = now or utcnow()
    session = SurveySession(
        survey_id=survey.id,
        respondent_id=respondent.id,
        status=SESSION_ACTIVE,
        current_position=0,
        started_at=now,
        last_message_at=now,
    )
    db.add(session)
    db.flush()  # session.respondent/survey relationships usable below

    sent = []
    if survey.intro_text:
        sent.append(_send(db, gateway, respondent.phone, survey.intro_text))
    sent.extend(_advance(db, session, gateway, from_position=0))
    db.commit()
    return sent


def dispatch_survey(
    db: Session,
    survey: Survey,
    gateway: SmsGateway,
    site: str | None = None,
    resend: bool = False,
    limit: int | None = None,
) -> dict:
    """Start the survey for every eligible respondent. Returns counts."""
    query = select(Respondent).where(Respondent.opted_out == False)  # noqa: E712
    if site:
        query = query.where(Respondent.site == site)
    respondents = db.scalars(query).all()

    sent = skipped = 0
    for respondent in respondents:
        if limit is not None and sent >= limit:
            break
        if start_survey(db, survey, respondent, gateway, resend=resend):
            sent += 1
        else:
            skipped += 1
    return {"sent": sent, "skipped": skipped}


def handle_inbound(db: Session, phone: str, text: str, gateway: SmsGateway) -> list[str]:
    """Process one inbound SMS. Returns the bodies of any replies sent."""
    try:
        phone = normalize_phone(phone, get_settings().default_country)
    except PhoneError:
        pass  # log the raw number; it just won't match a respondent

    db.add(MessageLog(phone=phone, direction="in", body=text, provider=gateway.name))

    respondent = db.scalar(select(Respondent).where(Respondent.phone == phone))
    if respondent is None:
        # Don't reply to strangers: every outbound SMS costs money.
        logger.info("Ignoring inbound from unknown number %s", phone)
        db.commit()
        return []

    cleaned = text.strip()

    if cleaned.lower() in OPT_OUT_KEYWORDS:
        respondent.opted_out = True
        for session in db.scalars(
            select(SurveySession).where(
                SurveySession.respondent_id == respondent.id,
                SurveySession.status == SESSION_ACTIVE,
            )
        ):
            session.status = SESSION_OPTED_OUT
        replies = [_send(db, gateway, phone, t(respondent.language, "opted_out"))]
        db.commit()
        return replies

    session = db.scalar(
        select(SurveySession).where(
            SurveySession.respondent_id == respondent.id,
            SurveySession.status == SESSION_ACTIVE,
        )
    )
    if session is None:
        logger.info("Inbound from %s with no active session: %r", phone, text)
        db.commit()
        return []

    lang = respondent.language
    question = next(
        (q for q in session.survey.questions if q.position == session.current_position), None
    )
    if question is None:  # survey edited underneath an open session
        logger.error(
            "Session %s points at missing position %s", session.id, session.current_position
        )
        session.status = SESSION_EXPIRED
        db.commit()
        return []

    session.last_message_at = utcnow()
    value, ok = validate_answer(question, cleaned)
    replies: list[str] = []

    if not ok:
        session.invalid_count += 1
        if session.invalid_count == 1:
            # Operating rule: send SYS_INVALID once...
            replies.append(_send(db, gateway, phone, t(lang, "invalid")))
            db.commit()
            return replies
        # ...then accept the next reply as given, so the session never stalls.
        value, is_valid = cleaned, False
    else:
        is_valid = True

    db.add(
        Answer(
            session_id=session.id,
            question_id=question.id,
            raw_text=cleaned,
            value=value,
            is_valid=is_valid,
        )
    )
    if question.var:
        set_variable(db, respondent.id, question.var, value)
    _apply_sets(db, respondent, question, value)
    session.invalid_count = 0

    end_if = question.end_if or {}
    if end_if and str(value) == str(end_if.get("value")):
        if end_if.get("opt_out"):
            respondent.opted_out = True
            session.status = SESSION_OPTED_OUT
        else:
            session.status = SESSION_COMPLETED
            session.completed_at = utcnow()
        message = end_if.get("message")
        if message:
            replies.append(_send(db, gateway, phone, localized(message, lang)))
        db.commit()
        return replies

    replies.extend(_advance(db, session, gateway, from_position=question.position))
    db.commit()
    return replies
