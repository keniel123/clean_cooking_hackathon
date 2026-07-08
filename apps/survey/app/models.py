from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# single = reply with one number 1..choices; multi = comma-separated numbers;
# number = free numeric with optional min/max; yesno = YES/NO/NDIYO/HAPANA;
# text = free text; system = statement sent without expecting a reply.
QUESTION_TYPES = ("single", "multi", "number", "yesno", "text", "system")

SURVEY_MODULES = ("enrolment", "baseline", "weekly", "monthly", "quarterly", "rebaseline", "adhoc")

SESSION_ACTIVE = "active"
SESSION_COMPLETED = "completed"
SESSION_EXPIRED = "expired"
SESSION_OPTED_OUT = "opted_out"

ARMS = ("A", "B", "C")  # A: daytime credits, B: anytime (control), C: daytime double


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Respondent(Base):
    __tablename__ = "respondents"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # Household account ID — the join key to smart-meter data.
    account_id: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    site: Mapped[str | None] = mapped_column(String(120), index=True)  # village / minigrid site
    language: Mapped[str] = mapped_column(String(5), default="en")  # set by S0 at enrolment
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arm: Mapped[str | None] = mapped_column(String(1))  # credit-window experiment arm
    preferred_send_time: Mapped[str | None] = mapped_column(String(10))  # morning|midday|evening (B24)
    # Panel bookkeeping (schedule & rotation operating rules)
    missed_weekly_streak: Mapped[int] = mapped_column(Integer, default=0)
    completion_streak: Mapped[int] = mapped_column(Integer, default=0)
    rested: Mapped[bool] = mapped_column(Boolean, default=False)  # paused from weekly pulse
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # meter no., tariff, epc flag, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sessions: Mapped[list[SurveySession]] = relationship(back_populates="respondent")
    variables: Mapped[list[RespondentVariable]] = relationship(back_populates="respondent")


class RespondentVariable(Base):
    """Latest value of each survey variable per respondent (e.g. own_epc=3).

    This is what skip logic evaluates against — including conditions that
    reference answers given in earlier sessions. Answer rows keep the full
    history; this table keeps only the current value.
    """

    __tablename__ = "respondent_variables"
    __table_args__ = (UniqueConstraint("respondent_id", "var"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    respondent_id: Mapped[int] = mapped_column(ForeignKey("respondents.id"), index=True)
    var: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    respondent: Mapped[Respondent] = relationship(back_populates="variables")


class Survey(Base):
    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    module: Mapped[str] = mapped_column(String(20), default="adhoc")  # panel role
    reward_kwh: Mapped[float] = mapped_column(Float, default=0.0)  # credit on completion
    intro_text: Mapped[str | None] = mapped_column(Text)
    thanks_text: Mapped[str | None] = mapped_column(Text)  # used when reward_kwh == 0
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    questions: Mapped[list[Question]] = relationship(
        back_populates="survey", order_by="Question.position", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[SurveySession]] = relationship(back_populates="survey")


class Question(Base):
    """One step of a survey. The SMS text is sent verbatim (per language) —
    answer options are embedded in the text, as in the question bank."""

    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("survey_id", "position"),
        UniqueConstraint("survey_id", "key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"))
    position: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(80))  # QID: S0, B1, W2, ...
    var: Mapped[str | None] = mapped_column(String(80))  # codebook variable: hh_size, own_epc, ...
    qtype: Mapped[str] = mapped_column(String(10))
    texts: Mapped[dict] = mapped_column(JSON)  # {"en": "...", "sw": "..."}
    choices: Mapped[int | None] = mapped_column(Integer)  # single/multi: valid replies are 1..choices
    min_value: Mapped[int | None] = mapped_column(Integer)  # number questions
    max_value: Mapped[int | None] = mapped_column(Integer)
    # Conditions are lists of {"var": ..., "equals"/"not_equals"/"in": ...}, ANDed.
    # ask_if: ask only when all match. skip_if: skip when all match.
    ask_if: Mapped[list | None] = mapped_column(JSON)
    skip_if: Mapped[list | None] = mapped_column(JSON)
    # Respondent attribute this answer updates, e.g. S0 sets language:
    # {"attr": "language", "map": {"1": "sw", "2": "en"}}
    sets: Mapped[dict | None] = mapped_column(JSON)
    # End the survey early on a given answer (S1 consent refusal):
    # {"value": "no", "opt_out": true, "message": {"en": ..., "sw": ...}}
    end_if: Mapped[dict | None] = mapped_column(JSON)

    survey: Mapped[Survey] = relationship(back_populates="questions")


class SurveySession(Base):
    """One respondent's pass through one survey session."""

    __tablename__ = "survey_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    respondent_id: Mapped[int] = mapped_column(ForeignKey("respondents.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default=SESSION_ACTIVE, index=True)
    current_position: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    survey: Mapped[Survey] = relationship(back_populates="sessions")
    respondent: Mapped[Respondent] = relationship(back_populates="sessions")
    answers: Mapped[list[Answer]] = relationship(back_populates="session")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("session_id", "question_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("survey_sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)  # normalized code(s); raw text if is_valid=False
    # False when the reply never parsed and was accepted raw after one SYS_INVALID
    # re-prompt (operating rule: "send SYS_INVALID once, accept next reply").
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[SurveySession] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()


class Reward(Base):
    """Ledger of electricity credits earned. Delivery to meters happens in the
    utility's vending system — export pending rows and mark them delivered."""

    __tablename__ = "rewards"

    id: Mapped[int] = mapped_column(primary_key=True)
    respondent_id: Mapped[int] = mapped_column(ForeignKey("respondents.id"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("survey_sessions.id"))
    kwh: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(20))  # completion | streak_bonus
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | delivered
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    respondent: Mapped[Respondent] = relationship()


class MessageLog(Base):
    """Audit trail of every SMS in and out, regardless of whether it advanced a survey."""

    __tablename__ = "message_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    body: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
