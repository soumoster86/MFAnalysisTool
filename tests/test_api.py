"""API smoke tests."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_goal_plan() -> None:
    r = client.post(
        "/api/v1/goals/plan",
        json={
            "age": 30,
            "retirement_age": 50,
            "current_investment": 200000,
            "monthly_sip": 15000,
            "expected_return": 0.11,
            "n_simulations": 200,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "expected_corpus" in body
    assert "probability_of_success" in body


def test_chat_offline() -> None:
    r = client.post("/api/v1/chat", json={"message": "Explain alpha"})
    assert r.status_code == 200
    assert "reply" in r.json()
