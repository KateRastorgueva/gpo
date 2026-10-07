"""Отзывы: один на запрос, только на свой запрос, метрика средней оценки."""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

QUESTION_TEMPLATE = "feedback question {suffix}"


def _ask(
    client: TestClient, headers: dict[str, str], *, question: str, session_id: str
) -> str:
    response = client.post(
        f"{settings.API_V1_STR}/support/ask",
        headers=headers,
        json={"question": question, "session_id": session_id, "channel": "web"},
    )
    assert response.status_code == 200
    return response.json()["request_id"]


def _submit(
    client: TestClient,
    headers: dict[str, str],
    *,
    request_id: str,
    rating: int,
    comment: str | None = None,
) -> object:
    payload: dict[str, object] = {"request_id": request_id, "rating": rating}
    if comment is not None:
        payload["comment"] = comment
    return client.post(
        f"{settings.API_V1_STR}/support/feedback", json=payload, headers=headers
    )


def test_feedback_saved_once_per_request(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    session_id = f"feedback-{uuid.uuid4()}"
    question = f"feedback question {uuid.uuid4()}"
    request_id = _ask(
        client, normal_user_token_headers, question=question, session_id=session_id
    )

    created = _submit(
        client,
        normal_user_token_headers,
        request_id=request_id,
        rating=5,
        comment="  Спасибо, помогло  ",
    )
    assert created.status_code == 200
    body = created.json()
    assert body["rating"] == 5
    assert body["comment"] == "Спасибо, помогло"
    assert body["request_id"] == request_id
    assert body["user_id"] is not None

    # Один отзыв на запрос (V7)
    duplicate = _submit(
        client, normal_user_token_headers, request_id=request_id, rating=1
    )
    assert duplicate.status_code == 409


def test_feedback_validates_rating_and_ownership(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    session_id = f"feedback-owner-{uuid.uuid4()}"
    question = f"feedback owner question {uuid.uuid4()}"
    request_id = _ask(
        client, normal_user_token_headers, question=question, session_id=session_id
    )

    # Оценка вне 1..5 отклоняется схемой
    assert (
        _submit(
            client, normal_user_token_headers, request_id=request_id, rating=6
        ).status_code
        == 422
    )

    # Чужой запрос: отзыв недоступен (отвечаем как на несуществующий)
    foreign = _submit(
        client,
        superuser_token_headers,
        request_id=str(uuid.uuid4()),
        rating=4,
    )
    assert foreign.status_code == 404


def test_metrics_expose_average_rating(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    before = client.get(
        f"{settings.API_V1_STR}/admin/metrics", headers=superuser_token_headers
    )
    assert before.status_code == 200
    assert "average_rating" in before.json()

    session_id = f"feedback-metrics-{uuid.uuid4()}"
    question = f"feedback metrics question {uuid.uuid4()}"
    request_id = _ask(
        client, normal_user_token_headers, question=question, session_id=session_id
    )
    assert (
        _submit(
            client, normal_user_token_headers, request_id=request_id, rating=3
        ).status_code
        == 200
    )

    after = client.get(
        f"{settings.API_V1_STR}/admin/metrics", headers=superuser_token_headers
    )
    assert after.status_code == 200
    body = after.json()
    assert body["feedback_count"] >= 1
    assert 0.0 < body["average_rating"] <= 5.0
