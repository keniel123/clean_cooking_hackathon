"""Read/ops API. Day-to-day management is via the `survey` CLI; these
endpoints exist for dashboards and remote dispatch."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..engine import dispatch_survey
from ..gateways import get_gateway
from ..models import Respondent, Survey, SurveySession
from ..results import survey_results

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "provider": get_settings().sms_provider}


def _get_survey(db: Session, slug: str) -> Survey:
    survey = db.scalar(select(Survey).where(Survey.slug == slug))
    if survey is None:
        raise HTTPException(status_code=404, detail=f"No survey with slug {slug!r}")
    return survey


@router.get("/surveys")
def list_surveys(db: Session = Depends(get_db)) -> list[dict]:
    surveys = db.scalars(select(Survey).order_by(Survey.created_at)).all()
    out = []
    for survey in surveys:
        counts = dict(
            db.execute(
                select(SurveySession.status, func.count())
                .where(SurveySession.survey_id == survey.id)
                .group_by(SurveySession.status)
            ).all()
        )
        out.append(
            {
                "slug": survey.slug,
                "title": survey.title,
                "language": survey.language,
                "questions": len(survey.questions),
                "sessions": counts,
            }
        )
    return out


@router.get("/surveys/{slug}/results")
def get_results(slug: str, db: Session = Depends(get_db)) -> dict:
    survey = _get_survey(db, slug)
    columns, rows = survey_results(db, survey)
    return {"survey": slug, "columns": columns, "rows": rows}


@router.get("/respondents/{account_id}/responses")
def respondent_responses(account_id: str, db: Session = Depends(get_db)) -> dict:
    """One account's survey history, keyed by the smart-meter account ID.

    Shaped for the monitoring dashboard (apps/dashboard), whose customer page
    joins on the same account IDs the GridCook API serves. Answers are keyed
    by codebook variable (falling back to the QID); invalid-but-accepted
    replies appear as `INVALID:<raw text>`, as in the CSV export.
    """
    respondent = db.scalar(select(Respondent).where(Respondent.account_id == account_id))
    if respondent is None:
        raise HTTPException(status_code=404, detail=f"No respondent with account ID {account_id!r}")
    sessions = db.scalars(
        select(SurveySession)
        .where(SurveySession.respondent_id == respondent.id)
        .order_by(SurveySession.started_at)
    ).all()
    responses = []
    for session in sessions:
        answers = {}
        for answer in session.answers:
            question = answer.question
            answers[question.var or question.key] = (
                answer.value if answer.is_valid else f"INVALID:{answer.raw_text}"
            )
        responses.append(
            {
                "session_id": session.id,
                "survey": session.survey.slug,
                "title": session.survey.title,
                "module": session.survey.module,
                "status": session.status,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
                "answers": answers,
            }
        )
    return {
        "account_id": respondent.account_id,
        "phone": respondent.phone,
        "name": respondent.name,
        "site": respondent.site,
        "language": respondent.language,
        "consented_at": respondent.consented_at.isoformat() if respondent.consented_at else None,
        "arm": respondent.arm,
        "responses": responses,
    }


class DispatchRequest(BaseModel):
    site: str | None = None
    resend: bool = False
    limit: int | None = None


@router.post("/surveys/{slug}/dispatch")
def dispatch(slug: str, payload: DispatchRequest, db: Session = Depends(get_db)) -> dict:
    survey = _get_survey(db, slug)
    return dispatch_survey(
        db,
        survey,
        get_gateway(),
        site=payload.site,
        resend=payload.resend,
        limit=payload.limit,
    )
