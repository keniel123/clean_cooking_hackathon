"""GridCook integration: synthetic phones must match the dashboard's
derivation, imports must land as respondents, and the per-account responses
endpoint must serve a completed session's answers."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.engine import handle_inbound, start_survey
from app.gateways import get_gateway
from app.gridcook import display_name, import_accounts, synthetic_phone
from app.main import app
from app.models import Respondent
from app.phone import normalize_phone

ACCOUNTS = [
    {
        "account_id": "HH-0007",
        "account_type": "household",
        "entity_id": "HH-0007",
        "community_id": "oloika",
        "meter_status": "metered",
    },
    {
        "account_id": "BIZ-001",
        "account_type": "commercial",
        "entity_id": "BIZ-001",
        "community_id": "oloika",
        "meter_status": "metered",
    },
]


def test_synthetic_phone_matches_dashboard_derivation():
    # Expected values are what apps/dashboard's HttpDataProvider renders for
    # these accounts (FNV-1a over the account ID) — keep the two in sync.
    assert synthetic_phone("HH-0007") == "+254732026437"
    assert synthetic_phone("BIZ-001") == "+254778923396"


def test_synthetic_phones_are_valid_kenyan_mobiles():
    for i in range(50):
        phone = synthetic_phone(f"HH-{i:04d}")
        assert normalize_phone(phone) == phone


def test_import_accounts_is_idempotent(db):
    assert import_accounts(db, ACCOUNTS) == (2, 0)

    respondent = db.scalar(select(Respondent).where(Respondent.account_id == "HH-0007"))
    assert respondent.phone == "+254732026437"
    assert respondent.name == "Household HH-0007"
    assert respondent.site == "oloika"
    assert respondent.meta["phone_is_synthetic"] is True
    assert display_name(ACCOUNTS[1]) == "Business BIZ-001"

    assert import_accounts(db, ACCOUNTS) == (0, 2)


def test_responses_endpoint_serves_completed_session(db, survey, respondent):
    get_gateway.cache_clear()
    gateway = get_gateway()
    start_survey(db, survey, respondent, gateway)
    for text in ["4", "2,4", "0", "yes"]:  # Q3 skipped: no firewood in Q2
        handle_inbound(db, respondent.phone, text, gateway)

    with TestClient(app) as client:
        resp = client.get("/api/respondents/ACC-001/responses")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == "ACC-001"
        assert data["phone"] == respondent.phone
        assert len(data["responses"]) == 1
        session = data["responses"][0]
        assert session["survey"] == "test-survey"
        assert session["status"] == "completed"
        assert session["completed_at"] is not None
        assert session["answers"]["satisfaction"] == "4"
        assert session["answers"]["fuels"] == "2,4"
        assert "why_no_electric" not in session["answers"]  # skip logic respected


def test_responses_endpoint_unknown_account_404(db):
    with TestClient(app) as client:
        assert client.get("/api/respondents/NOPE-999/responses").status_code == 404
