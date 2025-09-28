import hashlib
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _stable_skill_id(name: str) -> str:
    return f"skill-{hashlib.sha1(name.lower().encode()).hexdigest()[:8]}"


def test_generate_skeleton_returns_characterskeleton_with_ranked_skills_and_stable_ids(monkeypatch: Any) -> None:
    # Arrange: patch DSPy predictor to return a deterministic list
    def fake_predict(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(
            high_concept="Witty Detective",
            trouble="Nosy in All the Wrong Places",
            ranked_skills=["Fight", "Stealth", "Lore"],
        )

    monkeypatch.setattr("app.routes.api.predict_skeleton_text", fake_predict)

    body = {
        "idea": "witty detective",
        "setting": "noir",
        "skillList": ["Fight", "Notice", "Stealth", "Lore"],
    }

    # Act
    res1 = client.post("/api/generate_skeleton", json=body)
    res2 = client.post("/api/generate_skeleton", json=body)

    # Assert
    assert res1.status_code == 200
    data1 = res1.json()
    assert set(data1.keys()) == {"highConcept", "trouble", "skills"}
    names1 = [s["name"] for s in data1["skills"]]
    ranks1 = [s["rank"] for s in data1["skills"]]
    ids1 = [s["id"] for s in data1["skills"]]

    # Order preserved from prediction, filtered to allowed, highest rank first
    assert names1 == ["Fight", "Stealth", "Lore"]
    assert ranks1 == [3, 2, 1]
    assert ids1[0] == _stable_skill_id("Fight")

    # Idempotency: same inputs -> same IDs
    data2 = res2.json()
    ids2 = [s["id"] for s in data2["skills"]]
    assert ids1 == ids2


def test_generate_skeleton_filters_and_dedupes_predicted_skills(monkeypatch: Any) -> None:
    def fake_predict(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(
            high_concept="Witty Detective",
            trouble="Nosy in All the Wrong Places",
            ranked_skills=["fight", "FIGHT", "Notice", "Unknown"],
        )

    monkeypatch.setattr("app.routes.api.predict_skeleton_text", fake_predict)

    body = {
        "idea": "witty detective",
        "setting": "noir",
        "skillList": ["Fight", "Notice"],
    }

    res = client.post("/api/generate_skeleton", json=body)
    assert res.status_code == 200
    data = res.json()
    names = [s["name"] for s in data["skills"]]
    assert names == ["Fight", "Notice"]  # deduped, filtered, canonicalized case


def test_generate_skeleton_fallback_when_prediction_empty(monkeypatch: Any) -> None:
    def fake_predict(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(high_concept="", trouble="", ranked_skills=[])

    monkeypatch.setattr("app.routes.api.predict_skeleton_text", fake_predict)

    provided = ["Fight", "Notice", "Stealth"]
    body = {
        "idea": "witty detective",
        "setting": "noir",
        "skillList": provided,
    }

    res = client.post("/api/generate_skeleton", json=body)
    assert res.status_code == 200
    data = res.json()
    names = [s["name"] for s in data["skills"]]
    ranks = [s["rank"] for s in data["skills"]]
    assert names == provided
    assert ranks == [3, 2, 1]
