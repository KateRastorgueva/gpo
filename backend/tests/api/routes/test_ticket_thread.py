"""Переписка по тикету: шаги обращения для оператора (GET /admin/tickets/{id}/thread)."""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

API = settings.API_V1_STR


def _queue(client: TestClient, headers: dict[str, str]) -> list[dict]:
    response = client.get(f"{API}/admin/operator-queue", headers=headers)
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


def test_ticket_thread_has_question_and_steps(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    question = f"Посоветуйте рецепт борща, кейс {uuid.uuid4()}"
    asked = client.post(
        f"{API}/support/ask",
        headers=normal_user_token_headers,
        json={"question": question, "channel": "web"},
    )
    assert asked.status_code == 200, asked.text

    ticket = next(item for item in _queue(client, superuser_token_headers) if item["question"] == question)
    thread = client.get(
        f"{API}/admin/tickets/{ticket['ticket_id']}/thread",
        headers=superuser_token_headers,
    )

    assert thread.status_code == 200, thread.text
    body = thread.json()
    assert body["question"] == question
    assert body["request_id"] == ticket["request_id"]
    assert body["steps"], "у обращения должен быть хотя бы один шаг обработки"
    assert all("answer" in step for step in body["steps"])


def test_ticket_thread_requires_ticket_read(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    # Создаём тикет, чтобы id был настоящим, и проверяем запрет обычному пользователю.
    question = f"Посоветуйте рецепт борща, кейс {uuid.uuid4()}"
    client.post(
        f"{API}/support/ask",
        headers=normal_user_token_headers,
        json={"question": question, "channel": "web"},
    )
    ticket = next(item for item in _queue(client, superuser_token_headers) if item["question"] == question)

    response = client.get(
        f"{API}/admin/tickets/{ticket['ticket_id']}/thread",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403
