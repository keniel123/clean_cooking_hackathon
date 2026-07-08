"""End-to-end tests of the real eCooking instruments in surveys/."""

from sqlalchemy import select

from app.engine import handle_inbound, set_variable, start_survey
from app.models import (
    SESSION_COMPLETED,
    SESSION_OPTED_OUT,
    Answer,
    Respondent,
    Reward,
    Survey,
)
from app.survey_loader import load_survey_directory

from tests.conftest import SURVEYS_DIR

PHONE = "+254712345678"


def _load(db):
    result = load_survey_directory(db, SURVEYS_DIR)
    return {slug: db.scalar(select(Survey).where(Survey.slug == slug)) for slug, _ in result["loaded"]}


def test_all_instruments_load_within_one_sms(db):
    result = load_survey_directory(db, SURVEYS_DIR)
    assert len(result["loaded"]) == 11
    # The design requires every message to fit one 160-char GSM-7 SMS.
    assert result["warnings"] == []


def test_enrolment_flow_swahili_consent_and_pass(db, respondent, gateway):
    surveys = _load(db)
    sent = start_survey(db, surveys["ecooking-enrolment"], respondent, gateway)
    assert "Hii ni TestGrid" in sent[0]  # {utility} substituted

    # S0: chooses Kiswahili -> everything after arrives in Swahili
    replies = handle_inbound(db, PHONE, "1", gateway)
    db.refresh(respondent)
    assert respondent.language == "sw"
    assert "Tunakualika" in replies[0]  # S1 in Swahili

    # S1: consents with NDIYO -> S2 (system) and C1 arrive together
    replies = handle_inbound(db, PHONE, "NDIYO", gateway)
    db.refresh(respondent)
    assert respondent.consented_at is not None
    assert "Asante kwa kujiunga" in replies[0]  # S2 system message
    assert "unayepika" in replies[1]  # C1

    # C1=3 (rarely cooks) -> SYS_PASS handover request, then completion reward
    replies = handle_inbound(db, PHONE, "3", gateway)
    assert "mwombe anayepika" in replies[0]  # SYS_PASS
    assert "units 0.5 za BURE" in replies[1]  # welcome credit, daytime wording

    reward = db.scalar(select(Reward))
    assert reward.kwh == 0.5
    assert reward.kind == "completion"


def test_consent_refusal_opts_out(db, respondent, gateway):
    surveys = _load(db)
    start_survey(db, surveys["ecooking-enrolment"], respondent, gateway)
    handle_inbound(db, PHONE, "2", gateway)  # English
    replies = handle_inbound(db, PHONE, "NO", gateway)
    assert "will not receive" in replies[0]
    db.refresh(respondent)
    assert respondent.opted_out
    assert db.scalar(select(Reward)) is None  # no credit without consent
    session = respondent.sessions[0]
    assert session.status == SESSION_OPTED_OUT


def test_pulse_skips_appliance_questions_without_epc_or_hob(db, respondent, gateway):
    surveys = _load(db)
    # Baseline said: no EPC (B7=3) and no hob (B8=3)
    set_variable(db, respondent.id, "own_epc", "3")
    set_variable(db, respondent.id, "own_hob", "3")
    db.commit()

    start_survey(db, surveys["ecooking-pulse-week-1"], respondent, gateway)
    handle_inbound(db, PHONE, "1,2", gateway)  # W1 fuels
    replies = handle_inbound(db, PHONE, "2", gateway)  # W2: did not cook midday
    assert "What stopped you" in replies[0]  # W3 asked because W2=2

    # W4 skipped (no appliances), W5 skipped (W4 never answered) -> completed
    replies = handle_inbound(db, PHONE, "1", gateway)
    session = db.scalar(select(Survey).where(Survey.slug == "ecooking-pulse-week-1")).sessions[0]
    assert session.status == SESSION_COMPLETED
    answered = {a.question.key for a in db.scalars(select(Answer))}
    assert answered == {"W1", "W2", "W3"}
    assert "0.4" in replies[0]  # pulse reward


def test_pulse_asks_appliance_questions_with_epc(db, respondent, gateway):
    surveys = _load(db)
    set_variable(db, respondent.id, "own_epc", "1")
    set_variable(db, respondent.id, "own_hob", "3")
    db.commit()

    start_survey(db, surveys["ecooking-pulse-week-1"], respondent, gateway)
    handle_inbound(db, PHONE, "4", gateway)  # W1: electricity
    replies = handle_inbound(db, PHONE, "1", gateway)  # W2: cooked midday
    assert "EPC or electric hob" in replies[0]  # W3 skipped, W4 asked

    replies = handle_inbound(db, PHONE, "2", gateway)  # W4: EPC only
    assert "cook with electricity this week" in replies[0]  # W5 follows W4 in 1-3


def test_quarterly_reasks_household_size_on_change(db, respondent, gateway):
    surveys = _load(db)
    start_survey(db, surveys["ecooking-quarterly"], respondent, gateway)
    for reply in ["1", "1", "1", "1"]:  # M1-M4
        handle_inbound(db, PHONE, reply, gateway)
    handle_inbound(db, PHONE, "1", gateway)  # Q1: more people
    handle_inbound(db, PHONE, "2", gateway)  # Q2: no new activity -> Q3 skipped
    handle_inbound(db, PHONE, "1", gateway)  # Q4
    handle_inbound(db, PHONE, "3", gateway)  # Q5
    replies = handle_inbound(db, PHONE, "Bei nafuu zaidi", gateway)  # Q6 free text
    assert "How many people" in replies[0]  # B1 re-asked because Q1=1

    handle_inbound(db, PHONE, "7", gateway)
    variables = {v.var: v.value for v in respondent.variables}
    assert variables["hh_size"] == "7"


def test_arm_c_doubles_reward_and_arm_b_gets_anytime_wording(db, gateway):
    surveys = _load(db)
    for phone, arm in [("+254700000001", "C"), ("+254700000002", "B")]:
        r = Respondent(phone=phone, arm=arm, language="en")
        db.add(r)
        db.commit()
        set_variable(db, r.id, "own_epc", "3")
        set_variable(db, r.id, "own_hob", "3")
        db.commit()
        start_survey(db, surveys["ecooking-pulse-week-2"], r, gateway)
        handle_inbound(db, phone, "1", gateway)  # W1
        handle_inbound(db, phone, "1", gateway)  # W2=1, W3 skipped, W6 skipped
        replies = handle_inbound(db, phone, "1", gateway)  # W7 -> completed
        if arm == "C":
            assert "0.8 FREE units" in replies[0]  # doubled
            assert "10am-3pm" in replies[0]
        else:
            assert "0.4 FREE units" in replies[0]
            assert "any time" in replies[0]
