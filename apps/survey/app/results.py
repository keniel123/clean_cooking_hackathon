"""Flatten survey answers into one row per session, one column per question.

Columns use codebook variable names (falling back to the QID); values are
numeric codes as stored — join the workbook's Codebook sheet for labels.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Answer, Survey, SurveySession


def survey_results(db: Session, survey: Survey) -> tuple[list[str], list[dict]]:
    """Returns (columns, rows) for CSV export or the JSON API."""
    questions = [q for q in survey.questions if q.qtype != "system"]
    id_columns = [
        "account_id", "phone", "name", "site", "arm",
        "status", "started_at", "completed_at",
    ]
    columns = id_columns + [q.var or q.key for q in questions]

    sessions = db.scalars(
        select(SurveySession)
        .where(SurveySession.survey_id == survey.id)
        .order_by(SurveySession.started_at)
    ).all()

    rows = []
    for session in sessions:
        answers = {
            a.question_id: a
            for a in db.scalars(select(Answer).where(Answer.session_id == session.id))
        }
        respondent = session.respondent
        row = {
            "account_id": respondent.account_id or "",
            "phone": respondent.phone,
            "name": respondent.name or "",
            "site": respondent.site or "",
            "arm": respondent.arm or "",
            "status": session.status,
            "started_at": session.started_at.isoformat() if session.started_at else "",
            "completed_at": session.completed_at.isoformat() if session.completed_at else "",
        }
        for q in questions:
            answer = answers.get(q.id)
            if answer is None:
                row[q.var or q.key] = ""
            elif answer.is_valid:
                row[q.var or q.key] = answer.value
            else:
                row[q.var or q.key] = f"INVALID:{answer.raw_text}"
        rows.append(row)
    return columns, rows
