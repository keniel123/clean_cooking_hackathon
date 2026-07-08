"""Browser demo: a feature-phone mock for walking through the survey flows.

Dev-only (gated by ENABLE_SIMULATOR, like /webhooks/simulate). GET /demo
serves the handset UI; replies typed on its keypad go through the real
engine via /webhooks/simulate, so the screen shows exactly what a
respondent's phone would receive. The endpoints here provide the message
thread, respondent state, and demo conveniences (reset, dispatch).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..engine import start_survey
from ..gateways import get_gateway
from ..models import (
    SESSION_ACTIVE,
    SESSION_EXPIRED,
    Answer,
    MessageLog,
    Respondent,
    RespondentVariable,
    Reward,
    Survey,
    SurveySession,
)
from ..phone import PhoneError, normalize_phone
from ..survey_loader import load_survey_directory

router = APIRouter(prefix="/demo", tags=["demo"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _guard() -> None:
    if not get_settings().enable_simulator:
        raise HTTPException(status_code=404)


def _normalize(phone: str) -> str:
    try:
        return normalize_phone(phone, get_settings().default_country)
    except PhoneError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def demo_page() -> FileResponse:
    _guard()
    return FileResponse(STATIC_DIR / "demo.html", media_type="text/html")


@router.get("/state")
def demo_state(phone: str, db: Session = Depends(get_db)) -> dict:
    _guard()
    phone = _normalize(phone)
    surveys = db.scalars(select(Survey.slug).order_by(Survey.slug)).all()
    respondent = db.scalar(select(Respondent).where(Respondent.phone == phone))
    if respondent is None:
        return {"registered": False, "surveys": surveys, "messages": []}

    messages = [
        {"direction": m.direction, "body": m.body, "at": m.created_at.isoformat()}
        for m in db.scalars(
            select(MessageLog)
            .where(MessageLog.phone == phone)
            .order_by(MessageLog.created_at, MessageLog.id)
        )
    ]
    active = db.scalar(
        select(SurveySession).where(
            SurveySession.respondent_id == respondent.id,
            SurveySession.status == SESSION_ACTIVE,
        )
    )
    active_info = None
    if active:
        question = next(
            (q for q in active.survey.questions if q.position == active.current_position), None
        )
        active_info = {
            "survey": active.survey.slug,
            "question": question.key if question else None,
            "var": question.var if question else None,
        }
    variables = {
        v.var: v.value
        for v in db.scalars(
            select(RespondentVariable)
            .where(RespondentVariable.respondent_id == respondent.id)
            .order_by(RespondentVariable.updated_at)
        )
    }
    rewards_kwh = db.scalar(
        select(func.coalesce(func.sum(Reward.kwh), 0.0)).where(
            Reward.respondent_id == respondent.id
        )
    )
    return {
        "registered": True,
        "surveys": surveys,
        "messages": messages,
        "respondent": {
            "phone": respondent.phone,
            "name": respondent.name,
            "site": respondent.site,
            "language": respondent.language,
            "consented": respondent.consented_at is not None,
            "opted_out": respondent.opted_out,
            "arm": respondent.arm,
            "preferred_send_time": respondent.preferred_send_time,
        },
        "active_session": active_info,
        "variables": variables,
        "rewards_kwh": rewards_kwh,
    }


class ResetRequest(BaseModel):
    phone: str
    name: str = "Demo Household"
    site: str = "Demo Village"


@router.post("/reset")
def demo_reset(payload: ResetRequest, db: Session = Depends(get_db)) -> dict:
    """Wipe the demo respondent and start fresh; load instruments if needed."""
    _guard()
    phone = _normalize(payload.phone)

    respondent = db.scalar(select(Respondent).where(Respondent.phone == phone))
    if respondent is not None:
        session_ids = db.scalars(
            select(SurveySession.id).where(SurveySession.respondent_id == respondent.id)
        ).all()
        if session_ids:
            db.execute(delete(Answer).where(Answer.session_id.in_(session_ids)))
        db.execute(delete(Reward).where(Reward.respondent_id == respondent.id))
        db.execute(delete(SurveySession).where(SurveySession.respondent_id == respondent.id))
        db.execute(
            delete(RespondentVariable).where(RespondentVariable.respondent_id == respondent.id)
        )
        db.execute(delete(MessageLog).where(MessageLog.phone == phone))
        db.delete(respondent)
        db.flush()

    db.add(Respondent(phone=phone, name=payload.name, site=payload.site, account_id=f"DEMO-{phone[-6:]}"))

    loaded = 0
    if db.scalar(select(func.count(Survey.id))) == 0 and Path("surveys").is_dir():
        loaded = len(load_survey_directory(db, "surveys")["loaded"])
    db.commit()
    return {"ok": True, "instruments_loaded": loaded}


class DispatchRequest(BaseModel):
    phone: str
    slug: str


@router.post("/dispatch")
def demo_dispatch(payload: DispatchRequest, db: Session = Depends(get_db)) -> dict:
    """Send one instrument to the demo phone, closing any open session first
    (a demo convenience — the real scheduler never interrupts a session)."""
    _guard()
    phone = _normalize(payload.phone)
    respondent = db.scalar(select(Respondent).where(Respondent.phone == phone))
    if respondent is None:
        raise HTTPException(status_code=404, detail="No demo respondent — reset the demo first.")
    survey = db.scalar(select(Survey).where(Survey.slug == payload.slug))
    if survey is None:
        raise HTTPException(status_code=404, detail=f"No survey {payload.slug!r}.")
    if respondent.opted_out:
        return {
            "sent": 0,
            "note": "Respondent has opted out (STOP/ACHA or consent refusal) and can never be "
            "messaged again. Reset the demo to start over.",
        }

    for session in db.scalars(
        select(SurveySession).where(
            SurveySession.respondent_id == respondent.id,
            SurveySession.status == SESSION_ACTIVE,
        )
    ):
        session.status = SESSION_EXPIRED
    db.flush()

    sent = start_survey(db, survey, respondent, get_gateway(), resend=True)
    db.commit()
    return {"sent": len(sent)}
