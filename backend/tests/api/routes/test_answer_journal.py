"""Журнал ответов как шаги обработки: 1:N на запрос, финальность, поле steps в истории."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import FaqEntryCreate, SupportAnswer, SupportRequest, User
from app.services.support_service import create_faq_entry


def _ask(
    client: TestClient,
    headers: dict[str, str],
    *,
    question: str,
    session_id: str,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/support/ask",
        headers=headers,
        json={"question": question, "session_id": session_id, "channel": "web"},
    )
    assert response.status_code == 200


def _request(db: Session, session_id: str) -> SupportRequest:
    db.expire_all()
    return db.exec(
        select(SupportRequest).where(SupportRequest.session_id == session_id)
    ).one()


def _entries(db: Session, request_id: uuid.UUID) -> list[SupportAnswer]:
    db.expire_all()
    return list(
        db.exec(
            select(SupportAnswer)
            .where(col(SupportAnswer.request_id) == request_id)
            .order_by(col(SupportAnswer.step_index))
        ).all()
    )


def test_faq_answer_creates_single_final_step(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    session_id = f"journal-faq-{uuid.uuid4()}"
    question = f"journal faq question {uuid.uuid4()}"
    faq = create_faq_entry(
        db, FaqEntryCreate(question=question, answer="Ответ из FAQ", is_active=True)
    )

    _ask(client, normal_user_token_headers, question=question, session_id=session_id)

    request = _request(db, session_id)
    entries = _entries(db, request.id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.step == "faq"
    assert entry.step_index == 0
    assert entry.is_final is True
    assert entry.answer == "Ответ из FAQ"
    assert entry.performed_by is None
    assert entry.knowledge_id == faq.id
    assert entry.response_time_ms is not None
    assert entry.response_time_ms >= 0


def test_escalation_step_is_not_final(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    session_id = f"journal-escalation-{uuid.uuid4()}"
    question = f"journal escalation question {uuid.uuid4()}"

    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch("app.services.support_service.retrieve_relevant_chunks", return_value=[]),
    ):
        _ask(
            client,
            superuser_token_headers,
            question=question,
            session_id=session_id,
        )

    request = _request(db, session_id)
    entries = _entries(db, request.id)
    assert len(entries) == 1
    assert entries[0].step == "operator"
    # Запрос ждёт оператора: автоматический шаг не завершает обработку
    assert entries[0].is_final is False
    assert entries[0].knowledge_id is None


def test_history_exposes_steps_and_keeps_answer(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    session_id = f"journal-history-{uuid.uuid4()}"
    question = f"journal history question {uuid.uuid4()}"
    create_faq_entry(
        db, FaqEntryCreate(question=question, answer="Исторический ответ", is_active=True)
    )
    _ask(client, normal_user_token_headers, question=question, session_id=session_id)

    response = client.get(
        f"{settings.API_V1_STR}/support/history",
        params={"session_id": session_id},
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    entry = body["data"][0]
    # Прежний контракт сохранён
    assert entry["answer"] == "Исторический ответ"
    assert entry["mode"] == "faq"
    # И добавлены шаги
    assert len(entry["steps"]) == 1
    assert entry["steps"][0]["step"] == "faq"
    assert entry["steps"][0]["is_final"] is True
    assert entry["steps"][0]["created_at"] is not None


def test_multiple_steps_per_request_are_allowed(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    session_id = f"journal-multi-{uuid.uuid4()}"
    question = f"journal multi question {uuid.uuid4()}"
    create_faq_entry(
        db, FaqEntryCreate(question=question, answer="Автоответ", is_active=True)
    )
    _ask(client, normal_user_token_headers, question=question, session_id=session_id)

    request = _request(db, session_id)
    user = db.exec(select(User)).first()
    # Второй шаг того же запроса: снятие UNIQUE(request_id) — цель миграции M6
    db.add(
        SupportAnswer(
            request_id=request.id,
            step="human",
            step_index=1,
            performed_by=user.id if user else None,
            answer="Ответ оператора",
            is_final=True,
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/support/history",
        params={"session_id": session_id},
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    entry = response.json()["data"][0]
    assert [step["step"] for step in entry["steps"]] == ["faq", "human"]
    # Финальный шаг определяет поле answer
    assert entry["answer"] == "Ответ оператора"
    assert entry["steps"][1]["performed_by"] is not None


def test_step_index_is_unique_per_request(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    session_id = f"journal-unique-{uuid.uuid4()}"
    question = f"journal unique question {uuid.uuid4()}"
    create_faq_entry(db, FaqEntryCreate(question=question, answer="Ответ", is_active=True))
    _ask(client, normal_user_token_headers, question=question, session_id=session_id)

    request = _request(db, session_id)
    db.add(
        SupportAnswer(
            request_id=request.id,
            step="human",
            step_index=0,
            answer="Дубликат шага",
            is_final=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
