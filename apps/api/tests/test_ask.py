from fastapi.testclient import TestClient

from kb_api import main
from kb_core.models import Answer, Citation


class FakePipeline:
    def answer(self, question: str) -> Answer:
        return Answer(
            question=question,
            text="Use multiple Availability Zones [1].",
            citations=[Citation(1, "Framework", "Reliability", 12, "file:///f.pdf", 0.81234)],
            model="llama3.2",
            input_tokens=900,
            output_tokens=40,
        )


def test_ask_returns_answer_with_citations(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "get_pipeline", lambda: FakePipeline())
    response = TestClient(main.app).post("/ask", json={"question": "How do I stay available?"})
    assert response.status_code == 200
    body = response.json()
    assert body["citations"][0] == {
        "number": 1,
        "document_title": "Framework",
        "section": "Reliability",
        "page": 12,
        "similarity": 0.8123,
    }
    assert body["cost_usd"] == "0"


def test_ask_validates_input() -> None:
    response = TestClient(main.app).post("/ask", json={"question": "x"})
    assert response.status_code == 422
