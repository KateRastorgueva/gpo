"""Тикеты поддержки: назначение, ответ оператора, переоткрытие."""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import SupportRequest, SupportTicket


def _escalate(
    client: TestClient, headers: dict[str, str], *, session_id: str, question: str
) -> None:
    """Создать запрос, который уходит оператору (эскалация)."""
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch("app.services.support_service.retrieve_relevant_chunks", return_value=[]),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=headers,
            json={"question": question, "session_id": session_id, "channel": "web"},
        )
    assert response.status_code == 200
    assert response.json()["mode"] == "operator"


def _queue(client: TestClient, headers: dict[str, str]) -> list[dict]:
    response = client.get(
        f"{settings.API_V1_STR}/admin/operator-queue", headers=headers
    )
    assert response.status_code == 200
    return response.json()["data"]


def _ticket_for(client: TestClient, headers: dict[str, str], question: str) -> dict:
    return next(item for item in _queue(client, headers) if item["question"] == question)


def _request(db: Session, session_id: str) -> SupportRequest:
    db.expire_all()
    return db.exec(
        select(SupportRequest).where(SupportRequest.session_id == session_id)
    ).one()


def _active_request_ids(client: TestClient, headers: dict[str, str]) -> set[str]:
    response = client.get(
        f"{settings.API_V1_STR}/admin/requests/active", headers=headers
    )
    assert response.status_code == 200
    return {item["request_id"] for item in response.json()["data"]}


def test_escalation_creates_open_ticket(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    session_id = f"ticket-open-{uuid.uuid4()}"
    question = f"ticket open question {uuid.uuid4()}"
    _escalate(
        client, normal_user_token_headers, session_id=session_id, question=question
    )

    ticket = _ticket_for(client, superuser_token_headers, question)
    assert ticket["status"] == "open"
    assert ticket["assigned_to"] is None
    assert ticket["resolution"] is None
    assert ticket["reopened_from_id"] is None

    request = _request(db, session_id)
    assert request.status == "queued"
    assert str(request.id) in _active_request_ids(client, superuser_token_headers)


def test_assign_and_resolve_closes_request(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    session_id = f"ticket-resolve-{uuid.uuid4()}"
    question = f"ticket resolve question {uuid.uuid4()}"
    _escalate(
        client, normal_user_token_headers, session_id=session_id, question=question
    )
    ticket = _ticket_for(client, superuser_token_headers, question)

    assigned = client.post(
        f"{settings.API_V1_STR}/admin/tickets/{ticket['ticket_id']}/assign",
        json={"assigned_to": None},
        headers=superuser_token_headers,
    )
    assert assigned.status_code == 200

    resolved = client.post(
        f"{settings.API_V1_STR}/admin/tickets/{ticket['ticket_id']}/resolve",
        json={"resolution": "Обратитесь в деканат, кабинет 214."},
        headers=superuser_token_headers,
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["resolution"] == "Обратитесь в деканат, кабинет 214."
    assert body["resolved_at"] is not None
    assert body["assigned_to"] is not None

    # Запрос отвечен и вышел из очереди
    request = _request(db, session_id)
    assert request.status == "answered"
    assert request.answered_at is not None
    assert str(request.id) not in _active_request_ids(client, superuser_token_headers)

    # Ответ оператора попал в журнал шагом human и виден в истории
    history = client.get(
        f"{settings.API_V1_STR}/support/history",
        params={"session_id": session_id},
        headers=normal_user_token_headers,
    )
    assert history.status_code == 200
    entry = history.json()["data"][0]
    assert [step["step"] for step in entry["steps"]] == ["operator", "human"]
    assert entry["answer"] == "Обратитесь в деканат, кабинет 214."
    assert entry["steps"][1]["is_final"] is True
    assert entry["steps"][1]["performed_by"] is not None

    # Повторное решение того же тикета запрещено
    again = client.post(
        f"{settings.API_V1_STR}/admin/tickets/{ticket['ticket_id']}/resolve",
        json={"resolution": "Ещё раз"},
        headers=superuser_token_headers,
    )
    assert again.status_code == 409


def test_reopen_creates_new_ticket_and_returns_request_to_queue(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    session_id = f"ticket-reopen-{uuid.uuid4()}"
    question = f"ticket reopen question {uuid.uuid4()}"
    _escalate(
        client, normal_user_token_headers, session_id=session_id, question=question
    )
    ticket = _ticket_for(client, superuser_token_headers, question)

    assert (
        client.post(
            f"{settings.API_V1_STR}/admin/tickets/{ticket['ticket_id']}/resolve",
            json={"resolution": "Первый ответ"},
            headers=superuser_token_headers,
        ).status_code
        == 200
    )

    reopened = client.post(
        f"{settings.API_V1_STR}/admin/tickets/{ticket['ticket_id']}/reopen",
        json={"reason": "Пользователь вернулся с уточнением"},
        headers=superuser_token_headers,
    )
    assert reopened.status_code == 200
    new_ticket = reopened.json()
    assert new_ticket["ticket_id"] != ticket["ticket_id"]
    assert new_ticket["status"] == "open"
    assert new_ticket["reopened_from_id"] == ticket["ticket_id"]
    assert new_ticket["reason"] == "Пользователь вернулся с уточнением"

    # Прежний тикет остаётся решённым, активным может быть только один
    db.expire_all()
    tickets = db.exec(
        select(SupportTicket).where(SupportTicket.request_id == uuid.UUID(ticket["request_id"]))
    ).all()
    assert len(tickets) == 2
    statuses = sorted(ticket_row.status for ticket_row in tickets)
    assert statuses == ["open", "resolved"]

    # Запрос вернулся в очередь
    request = _request(db, session_id)
    assert request.status == "queued"
    assert request.answered_at is None
    assert str(request.id) in _active_request_ids(client, superuser_token_headers)

    # Повторное переоткрытие, пока есть активный тикет, запрещено
    conflict = client.post(
        f"{settings.API_V1_STR}/admin/tickets/{new_ticket['ticket_id']}/reopen",
        json={},
        headers=superuser_token_headers,
    )
    assert conflict.status_code == 409


def test_ticket_actions_require_permission(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    session_id = f"ticket-perm-{uuid.uuid4()}"
    question = f"ticket perm question {uuid.uuid4()}"
    _escalate(
        client, normal_user_token_headers, session_id=session_id, question=question
    )
    ticket = _ticket_for(client, superuser_token_headers, question)

    for action, payload in (
        ("assign", {"assigned_to": None}),
        ("resolve", {"resolution": "текст"}),
        ("reopen", {}),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/admin/tickets/{ticket['ticket_id']}/{action}",
            json=payload,
            headers=normal_user_token_headers,
        )
        assert response.status_code == 403, action

    missing = client.post(
        f"{settings.API_V1_STR}/admin/tickets/{uuid.uuid4()}/resolve",
        json={"resolution": "текст"},
        headers=superuser_token_headers,
    )
    assert missing.status_code == 404
