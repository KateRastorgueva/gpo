"""Жизненный цикл запроса: журнал (источник правды) + горячая очередь active_request.

См. docs/db-schema-implementation-plan.md, §0.3.
"""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import ActiveRequest, FaqEntryCreate, SupportRequest
from app.services.support_service import create_faq_entry


def _ask(
    client: TestClient,
    headers: dict[str, str],
    *,
    question: str,
    session_id: str,
) -> dict:
    response = client.post(
        f"{settings.API_V1_STR}/support/ask",
        headers=headers,
        json={"question": question, "session_id": session_id, "channel": "web"},
    )
    assert response.status_code == 200
    return response.json()


def _get_request(db: Session, session_id: str) -> SupportRequest:
    db.expire_all()
    return db.exec(
        select(SupportRequest).where(SupportRequest.session_id == session_id)
    ).one()


def test_answered_request_stays_out_of_active_queue(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    session_id = f"lifecycle-faq-{uuid.uuid4()}"
    question = f"lifecycle faq question {uuid.uuid4()}"
    create_faq_entry(
        db, FaqEntryCreate(question=question, answer="Ответ из FAQ", is_active=True)
    )

    body = _ask(
        client, normal_user_token_headers, question=question, session_id=session_id
    )
    assert body["mode"] == "faq"

    request = _get_request(db, session_id)
    assert request.status == "answered"
    assert request.answered_at is not None
    assert request.closed_at is None
    assert request.updated_at is not None
    # Отвеченный запрос в очереди не висит
    assert db.get(ActiveRequest, request.id) is None


def test_escalation_puts_request_into_active_queue(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    session_id = f"lifecycle-escalation-{uuid.uuid4()}"
    question = f"lifecycle escalation question {uuid.uuid4()}"

    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch("app.services.support_service.retrieve_relevant_chunks", return_value=[]),
    ):
        body = _ask(
            client, normal_user_token_headers, question=question, session_id=session_id
        )
    assert body["mode"] == "operator"
    assert body["escalated"] is True

    request = _get_request(db, session_id)
    assert request.status == "queued"
    assert request.answered_at is None

    active = db.get(ActiveRequest, request.id)
    assert active is not None
    assert active.question == question
    assert active.channel == "web"
    assert active.priority == 0
    assert active.assigned_to is None

    queue_response = client.get(
        f"{settings.API_V1_STR}/admin/requests/active",
        headers=superuser_token_headers,
    )
    assert queue_response.status_code == 200
    queue_body = queue_response.json()
    assert any(item["request_id"] == str(request.id) for item in queue_body["data"])


def test_journal_contains_all_requests_and_supports_status_filter(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    session_id = f"lifecycle-journal-{uuid.uuid4()}"
    question = f"lifecycle journal question {uuid.uuid4()}"
    create_faq_entry(
        db, FaqEntryCreate(question=question, answer="Ответ", is_active=True)
    )
    _ask(client, normal_user_token_headers, question=question, session_id=session_id)

    response = client.get(
        f"{settings.API_V1_STR}/admin/requests/journal",
        params={"status": "answered", "limit": 200},
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    assert all(item["status"] == "answered" for item in body["data"])
    assert any(
        item["question"] == question and item["answered_at"] is not None
        for item in body["data"]
    )

    # Без фильтра журнал содержит и активные, и отвеченные запросы
    all_response = client.get(
        f"{settings.API_V1_STR}/admin/requests/journal",
        params={"limit": 200},
        headers=superuser_token_headers,
    )
    assert all_response.status_code == 200
    statuses = {item["status"] for item in all_response.json()["data"]}
    assert statuses.issubset({"queued", "in_progress", "answered", "closed"})


def test_requests_endpoints_require_ticket_read(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    for path in ("/admin/requests/active", "/admin/requests/journal"):
        response = client.get(
            f"{settings.API_V1_STR}{path}", headers=normal_user_token_headers
        )
        assert response.status_code == 403, path
