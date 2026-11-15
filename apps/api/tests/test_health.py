from fastapi.testclient import TestClient

from kb_api.main import app


def test_health_reports_ok_and_provider() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_provider"] in {"ollama", "bedrock"}
