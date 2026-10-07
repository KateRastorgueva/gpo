import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import FaqEntryCreate
from app.services.support_service import (
    RetrievalResult,
    _merge_hybrid_results,
    create_faq_entry,
    faq_similarity,
    generate_answer,
    rerank_results,
)


def _make_retrieval_results(
    *,
    first_score: float,
    second_score: float,
    same_source: bool = True,
) -> list[RetrievalResult]:
    source_id = uuid.uuid4()
    second_source_id = source_id if same_source else uuid.uuid4()
    return [
        RetrievalResult(
            source_id=source_id,
            source_title="Source A",
            source_ref="https://example.edu/a",
            chunk_id=uuid.uuid4(),
            snippet="Support desk works on weekdays.",
            score=first_score,
        ),
        RetrievalResult(
            source_id=second_source_id,
            source_title="Source B",
            source_ref="https://example.edu/b",
            chunk_id=uuid.uuid4(),
            snippet="Requests are accepted via web portal.",
            score=second_score,
        ),
    ]


def _assert_decision_metrics_shape(body: dict) -> None:
    assert "decision_metrics" in body
    metrics = body["decision_metrics"]
    assert {"top_score", "relevant_chunks", "faq_score", "conflict", "critical"}.issubset(
        metrics.keys()
    )


def test_support_ask_uses_faq(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    question = f"where can i get enrollment certificate {uuid.uuid4()}"
    answer = "Use student portal"
    create_faq_entry(
        db, FaqEntryCreate(question=question, answer=answer, is_active=True)
    )

    response = client.post(
        f"{settings.API_V1_STR}/support/ask",
        headers=normal_user_token_headers,
        json={"question": question, "channel": "web"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "faq"
    assert body["escalated"] is False
    assert body["answer"] == answer
    assert len(body["sources"]) == 1
    assert body["sources"][0]["source_title"] == "FAQ"
    assert body["route_reason"] == "faq_hit"
    _assert_decision_metrics_shape(body)


def test_faq_similarity_handles_typical_paraphrase_keywords() -> None:
    canonical = "Где посмотреть расписание занятий ТУСУР?"
    paraphrased = "расписание тусур пары"
    score = faq_similarity(paraphrased, canonical)
    assert score >= settings.FAQ_SIMILARITY_THRESHOLD


def test_support_ask_uses_faq_for_paraphrased_typical_question(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    canonical_question = "Где посмотреть расписание занятий ТУСУР?"
    answer = "Расписание занятий ТУСУР публикуется на https://timetable.tusur.ru/."
    create_faq_entry(
        db,
        FaqEntryCreate(
            question=canonical_question,
            answer=answer,
            is_active=True,
        ),
    )

    response = client.post(
        f"{settings.API_V1_STR}/support/ask",
        headers=normal_user_token_headers,
        json={"question": "расписание тусур пары", "channel": "web"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "faq"
    assert body["escalated"] is False
    assert body["answer"] == answer
    assert body["route_reason"] == "faq_hit"
    _assert_decision_metrics_shape(body)


def test_support_ask_uses_rag_with_fallback_flag(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    fake_results = _make_retrieval_results(
        first_score=0.93, second_score=0.84, same_source=True
    )
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch(
            "app.services.support_service.retrieve_relevant_chunks",
            return_value=fake_results,
        ),
        patch(
            "app.services.support_service.generate_answer",
            return_value=("Use dean office or student portal", True),
        ),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": "how to request study certificate", "channel": "web"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "rag"
    assert body["escalated"] is False
    assert body["fallback_used"] is True
    assert len(body["sources"]) == 2
    assert body["route_reason"] == "rag_answer"
    _assert_decision_metrics_shape(body)


def test_support_ask_escalates_when_context_missing(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch("app.services.support_service.retrieve_relevant_chunks", return_value=[]),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": "rare question with no context", "channel": "web"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "operator"
    assert body["escalated"] is True
    assert body["route_reason"] == "insufficient_context"
    _assert_decision_metrics_shape(body)


def test_support_ask_escalates_on_retrieval_failure(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch(
            "app.services.support_service.retrieve_relevant_chunks",
            side_effect=RuntimeError("qdrant-down"),
        ),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": "what if retrieval fails", "channel": "web"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "operator"
    assert body["escalated"] is True
    assert body["route_reason"] == "retrieval_failure"
    _assert_decision_metrics_shape(body)


def test_support_ask_escalates_when_sources_conflict(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    # close scores + different source ids => conflict
    fake_results = _make_retrieval_results(
        first_score=0.82, second_score=0.80, same_source=False
    )
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch(
            "app.services.support_service.retrieve_relevant_chunks",
            return_value=fake_results,
        ),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": "conflicting sources case", "channel": "web"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "operator"
    assert body["escalated"] is True
    assert body["route_reason"] == "conflict"
    _assert_decision_metrics_shape(body)


def test_support_ask_escalates_critical_low_confidence(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    fake_results = _make_retrieval_results(
        first_score=0.75, second_score=0.71, same_source=True
    )
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch(
            "app.services.support_service.retrieve_relevant_chunks",
            return_value=fake_results,
        ),
        patch("app.services.support_service.is_critical_question", return_value=True),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": "critical timeline question", "channel": "web"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "operator"
    assert body["escalated"] is True
    assert body["route_reason"] == "critical_low_confidence"
    _assert_decision_metrics_shape(body)


def test_support_ask_marks_low_confidence_non_critical_answers(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    fake_results = _make_retrieval_results(
        first_score=0.75, second_score=0.71, same_source=True
    )
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch(
            "app.services.support_service.retrieve_relevant_chunks",
            return_value=fake_results,
        ),
        patch(
            "app.services.support_service.generate_answer",
            return_value=("Use web support form", False),
        ),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": "how to contact support", "channel": "web"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "rag"
    assert body["escalated"] is False
    assert "Требуется проверка актуальности" in body["answer"]
    assert body["route_reason"] == "rag_answer"
    _assert_decision_metrics_shape(body)


def test_support_history_filters_by_session(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    question = f"history faq {uuid.uuid4()}"
    create_faq_entry(
        db, FaqEntryCreate(question=question, answer="History answer", is_active=True)
    )

    session_id = f"history-{uuid.uuid4()}"
    for _ in range(2):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": question, "session_id": session_id, "channel": "web"},
        )
        assert response.status_code == 200

    history_response = client.get(
        f"{settings.API_V1_STR}/support/history?session_id={session_id}",
        headers=normal_user_token_headers,
    )
    assert history_response.status_code == 200
    body = history_response.json()
    assert body["count"] == 2
    assert all(item["mode"] == "faq" for item in body["data"])


def test_operator_queue_contains_escalated_request(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    question = f"operator queue case {uuid.uuid4()}"
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch("app.services.support_service.retrieve_relevant_chunks", return_value=[]),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": question, "channel": "web"},
        )
    assert response.status_code == 200
    assert response.json()["mode"] == "operator"

    queue_response = client.get(
        f"{settings.API_V1_STR}/admin/operator-queue",
        headers=superuser_token_headers,
    )
    assert queue_response.status_code == 200
    queue_body = queue_response.json()
    assert any(item["question"] == question for item in queue_body["data"])


def test_admin_faq_crud(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/admin/faq",
        headers=superuser_token_headers,
        json={
            "question": f"faq crud question {uuid.uuid4()}",
            "answer": "check student portal",
            "is_active": True,
        },
    )
    assert create_response.status_code == 200
    faq_id = create_response.json()["id"]

    list_response = client.get(
        f"{settings.API_V1_STR}/admin/faq", headers=superuser_token_headers
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] >= 1

    update_response = client.patch(
        f"{settings.API_V1_STR}/admin/faq/{faq_id}",
        headers=superuser_token_headers,
        json={"answer": "updated faq answer"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["answer"] == "updated faq answer"

    delete_response = client.delete(
        f"{settings.API_V1_STR}/admin/faq/{faq_id}",
        headers=superuser_token_headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "FAQ entry deleted successfully"


def test_generate_answer_falls_back_to_ollama() -> None:
    fake_results = [
        RetrievalResult(
            source_id=uuid.uuid4(),
            source_title="Rules",
            source_ref="https://example.edu/rules",
            chunk_id=uuid.uuid4(),
            snippet="Response is based on regulation",
            score=0.93,
        )
    ]
    with (
        patch(
            "app.services.support_service._generate_with_google",
            side_effect=RuntimeError("google-timeout"),
        ),
        patch(
            "app.services.support_service._generate_with_ollama",
            return_value="Fallback answer",
        ),
    ):
        answer, fallback_used = generate_answer("how support works", fake_results)

    assert answer == "Fallback answer"
    assert fallback_used is True


def test_merge_hybrid_results_preserves_semantic_only_score() -> None:
    semantic_results = [
        RetrievalResult(
            source_id=uuid.uuid4(),
            source_title="Semantic source",
            source_ref="https://example.edu/semantic",
            chunk_id=uuid.uuid4(),
            snippet="Модуль описывает учебный процесс.",
            score=0.95,
        )
    ]

    merged = _merge_hybrid_results(semantic_results=semantic_results, lexical_results=[])

    assert len(merged) == 1
    assert abs(merged[0].score - semantic_results[0].score) < 1e-9


def test_rerank_results_does_not_lower_semantic_only_hit() -> None:
    base_results = [
        RetrievalResult(
            source_id=uuid.uuid4(),
            source_title="Semantic source",
            source_ref="https://example.edu/semantic",
            chunk_id=uuid.uuid4(),
            snippet="Университет публикует регламент учебного процесса.",
            score=0.95,
        )
    ]

    reranked = rerank_results("оплата общежития сроки", base_results)

    assert len(reranked) == 1
    assert reranked[0].score >= base_results[0].score


def test_admin_support_metrics_endpoint(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/admin/metrics",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert {
        "total_requests",
        "faq_share",
        "rag_share",
        "operator_share",
        "average_confidence",
        "empty_sources_share",
    }.issubset(body.keys())
