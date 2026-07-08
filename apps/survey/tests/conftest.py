"""Test environment must be pinned before any app module is imported,
because settings are cached and the engine is created at import time.
conftest.py is imported before the test modules, so doing it here is safe."""

import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkstemp(suffix='.db')[1]}"
os.environ["SMS_PROVIDER"] = "console"
os.environ["DEFAULT_COUNTRY"] = "KE"
os.environ["ENABLE_SIMULATOR"] = "true"
os.environ["TWILIO_VALIDATE_SIGNATURE"] = "false"
os.environ["UTILITY_NAME"] = "TestGrid"

from pathlib import Path

import pytest

from app.db import Base, SessionLocal, engine
from app.gateways.console import ConsoleGateway
from app.models import Question, Respondent, Survey

SURVEYS_DIR = Path(__file__).parent.parent / "surveys"


@pytest.fixture()
def db():
    import app.models  # noqa: F401  register tables

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def gateway():
    return ConsoleGateway()


@pytest.fixture()
def survey(db):
    """A small survey exercising every question type and both condition kinds."""
    s = Survey(slug="test-survey", title="Test survey", module="adhoc", thanks_text="Thank you!")
    s.questions = [
        Question(
            position=1, key="Q1", var="satisfaction", qtype="single", choices=5,
            texts={"en": "How satisfied are you? 1=Very 5=Not at all",
                   "sw": "Umeridhika kiasi gani? 1=Sana 5=La hasha"},
        ),
        Question(
            position=2, key="Q2", var="fuels", qtype="multi", choices=4,
            texts={"en": "Which fuels did you use? Reply all, e.g. 1,3: 1=Wood 2=Charcoal 3=LPG 4=Electric"},
        ),
        Question(
            position=3, key="Q3", var="why_no_electric", qtype="single", choices=3,
            ask_if=[{"var": "fuels", "contains": 1}],
            texts={"en": "Why firewood? 1=Cost 2=Taste 3=Habit"},
        ),
        Question(
            position=4, key="Q4", var="outages", qtype="number", min_value=0, max_value=99,
            texts={"en": "How many power cuts last week? Reply with a number."},
        ),
        Question(
            position=5, key="Q5", var="pay_ease", qtype="yesno",
            texts={"en": "Was it easy to buy tokens? Reply YES or NO."},
        ),
    ]
    db.add(s)
    db.commit()
    return s


@pytest.fixture()
def respondent(db):
    r = Respondent(
        phone="+254712345678", account_id="ACC-001", name="Wanjiku", site="Kisii", language="en"
    )
    db.add(r)
    db.commit()
    return r
