from fastapi.testclient import TestClient

from app.main import app

PHONE = "0712345678"


def _client():
    return TestClient(app)


def test_demo_page_served(db):
    with _client() as client:
        resp = client.get("/demo")
        assert resp.status_code == 200
        assert "M·GRID" in resp.text


def test_demo_full_cycle(db):
    with _client() as client:
        # unknown number: page still works, shows unregistered state
        state = client.get("/demo/state", params={"phone": PHONE}).json()
        assert state["registered"] is False

        # reset creates the respondent and loads the instruments on a fresh DB
        resp = client.post("/demo/reset", json={"phone": PHONE})
        assert resp.status_code == 200
        assert resp.json()["instruments_loaded"] == 11

        # dispatch enrolment, answer S0+S1+C1 through the simulate webhook
        resp = client.post("/demo/dispatch", json={"phone": PHONE, "slug": "ecooking-enrolment"})
        assert resp.json()["sent"] == 1
        for text in ["2", "YES", "1"]:
            client.post("/webhooks/simulate", json={"from": PHONE, "text": text})

        state = client.get("/demo/state", params={"phone": PHONE}).json()
        assert state["respondent"]["consented"] is True
        assert state["variables"]["main_cook"] == "1"
        assert state["rewards_kwh"] == 0.5
        assert state["active_session"] is None
        assert any("You earned 0.5" in m["body"] for m in state["messages"])

        # dispatching while a session is open force-closes it (demo convenience)
        client.post("/demo/dispatch", json={"phone": PHONE, "slug": "ecooking-baseline-1"})
        resp = client.post("/demo/dispatch", json={"phone": PHONE, "slug": "ecooking-pulse-week-1"})
        assert resp.json()["sent"] == 1
        state = client.get("/demo/state", params={"phone": PHONE}).json()
        assert state["active_session"]["survey"] == "ecooking-pulse-week-1"
        assert state["active_session"]["question"] == "W1"

        # reset wipes everything
        client.post("/demo/reset", json={"phone": PHONE})
        state = client.get("/demo/state", params={"phone": PHONE}).json()
        assert state["messages"] == []
        assert state["variables"] == {}


def test_opted_out_respondent_cannot_be_dispatched(db):
    with _client() as client:
        client.post("/demo/reset", json={"phone": PHONE})
        client.post("/demo/dispatch", json={"phone": PHONE, "slug": "ecooking-enrolment"})
        client.post("/webhooks/simulate", json={"from": PHONE, "text": "2"})
        client.post("/webhooks/simulate", json={"from": PHONE, "text": "STOP"})

        resp = client.post("/demo/dispatch", json={"phone": PHONE, "slug": "ecooking-baseline-1"})
        assert resp.json()["sent"] == 0
        assert "opted out" in resp.json()["note"]
