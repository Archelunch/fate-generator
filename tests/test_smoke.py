from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_serves_html() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Fate Generator" in res.text


def test_generate_skeleton_stub() -> None:
    res = client.post("/api/generate_skeleton")
    assert res.status_code == 200
    data = res.json()
    assert data["id"]
    assert data["meta"]["idea"]
