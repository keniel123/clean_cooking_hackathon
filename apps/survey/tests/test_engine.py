from sqlalchemy import select

from app.engine import handle_inbound, start_survey, validate_answer
from app.models import (
    SESSION_COMPLETED,
    SESSION_OPTED_OUT,
    Answer,
    MessageLog,
    Question,
    SurveySession,
)

PHONE = "+254712345678"


def _session(db):
    return db.scalar(select(SurveySession))


def _answers(db):
    return {a.question.var: a.value for a in db.scalars(select(Answer))}


def test_full_flow_with_conditions(db, survey, respondent, gateway):
    sent = start_survey(db, survey, respondent, gateway)
    assert sent == ["How satisfied are you? 1=Very 5=Not at all"]

    replies = handle_inbound(db, PHONE, "4", gateway)
    assert "Which fuels" in replies[0]

    # multi-select: messy separators normalise; "1" present -> Q3 is asked
    replies = handle_inbound(db, PHONE, "3, 1", gateway)
    assert "Why firewood" in replies[0]

    replies = handle_inbound(db, PHONE, "2", gateway)
    assert "power cuts" in replies[0]

    replies = handle_inbound(db, PHONE, "2", gateway)
    assert "easy to buy tokens" in replies[0]

    replies = handle_inbound(db, PHONE, "yes", gateway)
    assert replies == ["Thank you!"]

    assert _session(db).status == SESSION_COMPLETED
    assert _answers(db) == {
        "satisfaction": "4",
        "fuels": "1,3",  # sorted, comma-joined codes
        "why_no_electric": "2",
        "outages": "2",
        "pay_ease": "yes",
    }


def test_conditional_question_skipped(db, survey, respondent, gateway):
    start_survey(db, survey, respondent, gateway)
    handle_inbound(db, PHONE, "4", gateway)
    # no firewood in the multi answer -> Q3 skipped, straight to Q4
    replies = handle_inbound(db, PHONE, "2,4", gateway)
    assert "power cuts" in replies[0]
    handle_inbound(db, PHONE, "0", gateway)
    handle_inbound(db, PHONE, "no", gateway)
    answers = _answers(db)
    assert "why_no_electric" not in answers
    assert _session(db).status == SESSION_COMPLETED


def test_invalid_reply_prompts_once_then_accepts_raw(db, survey, respondent, gateway):
    start_survey(db, survey, respondent, gateway)

    replies = handle_inbound(db, PHONE, "banana", gateway)
    assert "did not understand" in replies[0]  # SYS_INVALID, question not re-sent

    # operating rule: the next reply is accepted as given, valid or not
    replies = handle_inbound(db, PHONE, "still banana", gateway)
    assert "Which fuels" in replies[0]  # survey moved on
    answer = db.scalar(select(Answer))
    assert answer.value == "still banana"
    assert answer.is_valid is False


def test_valid_reply_after_invalid_is_normal(db, survey, respondent, gateway):
    start_survey(db, survey, respondent, gateway)
    handle_inbound(db, PHONE, "9", gateway)  # out of range -> SYS_INVALID
    handle_inbound(db, PHONE, "2", gateway)
    answer = db.scalar(select(Answer))
    assert answer.value == "2"
    assert answer.is_valid is True


def test_number_range_enforced(db, survey, respondent, gateway):
    q = Question(position=1, key="B1", var="hh_size", qtype="number", min_value=1, max_value=30,
                 texts={"en": "How many people?"})
    assert validate_answer(q, "31") == (None, False)
    assert validate_answer(q, "0") == (None, False)
    assert validate_answer(q, "5") == ("5", True)


def test_multi_validation(db):
    q = Question(position=1, key="W1", var="w", qtype="multi", choices=5, texts={"en": "x"})
    assert validate_answer(q, "1,4") == ("1,4", True)
    assert validate_answer(q, "4 , 1, 4") == ("1,4", True)
    assert validate_answer(q, "5") == ("5", True)
    assert validate_answer(q, "1,6") == (None, False)
    assert validate_answer(q, "1,banana") == (None, False)
    assert validate_answer(q, "") == (None, False)


def test_stop_opts_out(db, survey, respondent, gateway):
    start_survey(db, survey, respondent, gateway)
    replies = handle_inbound(db, PHONE, "STOP", gateway)
    assert "left the survey" in replies[0]
    assert _session(db).status == SESSION_OPTED_OUT
    db.refresh(respondent)
    assert respondent.opted_out
    assert start_survey(db, survey, respondent, gateway, resend=True) == []


def test_acha_opts_out_in_swahili(db, survey, respondent, gateway):
    respondent.language = "sw"
    db.commit()
    start_survey(db, survey, respondent, gateway)
    replies = handle_inbound(db, PHONE, "ACHA", gateway)
    assert "Umeondoka" in replies[0]


def test_unknown_number_gets_no_reply(db, survey, respondent, gateway):
    start_survey(db, survey, respondent, gateway)
    assert handle_inbound(db, "+254799999999", "hello?", gateway) == []
    log = db.scalar(select(MessageLog).where(MessageLog.direction == "in"))
    assert log.phone == "+254799999999"


def test_no_double_dispatch(db, survey, respondent, gateway):
    assert len(start_survey(db, survey, respondent, gateway)) == 1
    assert start_survey(db, survey, respondent, gateway) == []  # already active
