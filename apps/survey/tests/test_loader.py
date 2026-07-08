import pytest

from app.engine import start_survey
from app.gateways.console import ConsoleGateway
from app.models import Respondent
from app.survey_loader import SurveyDefinitionError, load_survey_from_yaml

from tests.conftest import SURVEYS_DIR

ENROLMENT = SURVEYS_DIR / "ecooking-enrolment.yaml"


def test_loads_enrolment_instrument(db):
    survey, created, warnings = load_survey_from_yaml(db, ENROLMENT)
    assert created
    assert survey.module == "enrolment"
    assert survey.reward_kwh == 0.5
    assert [q.key for q in survey.questions] == ["S0", "S1", "S2", "C1", "SYS_PASS"]
    s1 = survey.questions[1]
    assert s1.qtype == "yesno"
    assert s1.end_if["opt_out"] is True
    assert survey.questions[4].ask_if == [{"var": "main_cook", "equals": 3}]


def test_reload_before_dispatch_is_allowed(db):
    load_survey_from_yaml(db, ENROLMENT)
    survey, created, _ = load_survey_from_yaml(db, ENROLMENT)
    assert not created
    assert len(survey.questions) == 5


def test_reload_after_dispatch_is_refused(db):
    survey, _, _ = load_survey_from_yaml(db, ENROLMENT)
    respondent = Respondent(phone="+254712345678")
    db.add(respondent)
    db.commit()
    start_survey(db, survey, respondent, ConsoleGateway())

    with pytest.raises(SurveyDefinitionError, match="already been dispatched"):
        load_survey_from_yaml(db, ENROLMENT)


@pytest.mark.parametrize(
    ("snippet", "match"),
    [
        ("questions:\n  - key: q1\n    type: single\n    var: v\n    text: {en: Pick}\n", "choices"),
        ("questions:\n  - key: q1\n    type: single\n    choices: 3\n    text: {en: Pick}\n", "need a 'var'"),
        ("questions:\n  - key: q1\n    type: wat\n    var: v\n    text: {en: Pick}\n", "unknown type"),
        ("questions:\n  - key: q1\n    type: text\n    var: v\n    text: {en: Q}\n    ask_if: [{var: x}]\n", "needs one of"),
        ("questions:\n  - key: q1\n    type: text\n    var: v\n    text: \"plain string\"\n", "mapping of language"),
    ],
)
def test_rejects_bad_definitions(db, tmp_path, snippet, match):
    bad = tmp_path / "bad.yaml"
    bad.write_text(f"slug: bad\ntitle: Bad\n{snippet}")
    with pytest.raises(SurveyDefinitionError, match=match):
        load_survey_from_yaml(db, bad)
