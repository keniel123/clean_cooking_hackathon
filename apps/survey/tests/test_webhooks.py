from fastapi.testclient import TestClient
from sqlalchemy import select

from app.engine import start_survey
from app.gateways import get_gateway
from app.main import app
from app.models import SESSION_COMPLETED, Answer, SurveySession

PHONE = "+254712345678"


def _client():
    return TestClient(app)


def _start(db, survey, respondent):
    get_gateway.cache_clear()
    start_survey(db, survey, respondent, get_gateway())


def test_simulate_endpoint_advances_survey(db, survey, respondent):
    _start(db, survey, respondent)
    with _client() as client:
        resp = client.post("/webhooks/simulate", json={"from": PHONE, "text": "4"})
        assert resp.status_code == 200
        assert "Which fuels" in resp.json()["replies"][0]


def test_twilio_webhook(db, survey, respondent):
    _start(db, survey, respondent)
    with _client() as client:
        resp = client.post("/webhooks/twilio", data={"From": PHONE, "Body": "5"})
        assert resp.status_code == 200
        assert "<Response></Response>" in resp.text

    answer = db.scalar(select(Answer))
    assert answer.value == "5"


def test_africastalking_webhook_full_completion(db, survey, respondent):
    _start(db, survey, respondent)
    with _client() as client:
        for text in ["4", "2,4", "0", "yes"]:  # Q3 skipped: no firewood in Q2
            resp = client.post("/webhooks/africastalking", data={"from": PHONE, "text": text})
            assert resp.status_code == 200

    session = db.scalar(select(SurveySession))
    assert session.status == SESSION_COMPLETED


def test_results_api(db, survey, respondent):
    _start(db, survey, respondent)
    with _client() as client:
        client.post("/webhooks/simulate", json={"from": PHONE, "text": "4"})

        resp = client.get("/api/surveys/test-survey/results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["columns"][:2] == ["account_id", "phone"]
        assert data["columns"][-5:] == ["satisfaction", "fuels", "why_no_electric", "outages", "pay_ease"]
        assert data["rows"][0]["satisfaction"] == "4"
        assert data["rows"][0]["account_id"] == "ACC-001"

        assert client.get("/api/surveys/nope/results").status_code == 404


def test_health(db):
    with _client() as client:
        resp = client.get("/api/health")
        assert resp.json() == {"status": "ok", "provider": "console"}
