"""Классификатор тем (модель Кати): тема пишется в журнал, ошибки не мешают ответу."""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.core.config import settings
from app.core.db import engine
from app.models import AppSetting, FaqEntryCreate, SupportRequest
from app.services import app_config, intent_classifier
from app.services.support_service import create_faq_entry

API = settings.API_V1_STR
RealClient = httpx.Client


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    with Session(engine) as session:
        session.execute(delete(AppSetting))
        session.commit()
    app_config.invalidate_cache()


def _fake_service(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    def _client(*args: Any, **kwargs: Any) -> httpx.Client:
        return RealClient(*args, transport=httpx.MockTransport(_record), **kwargs)

    monkeypatch.setattr(intent_classifier.httpx, "Client", _client)
    return calls


def _answer(
    category: str, confidence: float
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True, "error": None})
        return httpx.Response(
            200,
            json={
                "category": category,
                "label": category,
                "confidence": confidence,
                "candidates": [
                    {"category": category, "label": category, "confidence": confidence}
                ],
            },
        )

    return handler


def _enable(
    client: TestClient, headers: dict[str, str], threshold: float = 0.5
) -> None:
    r = client.put(
        f"{API}/admin/settings",
        headers=headers,
        json={
            "values": {
                "INTENT_CLASSIFIER_ENABLED": True,
                "INTENT_CLASSIFIER_THRESHOLD": threshold,
            }
        },
    )
    assert r.status_code == 200, r.text


def _ask_faq(client: TestClient, headers: dict[str, str], db: Session) -> str:
    question = f"как получить стипендию {uuid.uuid4()}"
    create_faq_entry(
        db, FaqEntryCreate(question=question, answer="Через деканат", is_active=True)
    )
    r = client.post(f"{API}/support/ask", headers=headers, json={"question": question})
    assert r.status_code == 200, r.text
    return str(r.json()["request_id"])


def _stored(request_id: str) -> SupportRequest:
    with Session(engine) as session:
        row = session.exec(
            select(SupportRequest).where(SupportRequest.id == uuid.UUID(request_id))
        ).one()
        return row


def test_disabled_by_default_and_service_not_called(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_service(monkeypatch, _answer("stipendiya", 0.9))
    request_id = _ask_faq(client, normal_user_token_headers, db)
    row = _stored(request_id)
    assert row.intent is None and row.intent_confidence is None
    assert calls == []


def test_enabled_writes_intent_to_journal_and_metrics(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_service(monkeypatch, _answer("stipendiya", 0.91))
    _enable(client, superuser_token_headers)
    request_id = _ask_faq(client, normal_user_token_headers, db)

    row = _stored(request_id)
    assert row.intent == "stipendiya"
    assert row.intent_confidence == pytest.approx(0.91)

    journal = client.get(
        f"{API}/admin/requests/journal", headers=superuser_token_headers
    ).json()
    entry = next(e for e in journal["data"] if e["request_id"] == request_id)
    assert entry["intent_label"] == "Стипендия"

    metrics = client.get(f"{API}/admin/metrics", headers=superuser_token_headers).json()
    topic = next(m for m in metrics["by_intent"] if m["intent"] == "stipendiya")
    assert topic["label"] == "Стипендия" and topic["total"] >= 1


def test_below_threshold_is_not_stored(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_service(monkeypatch, _answer("sport", 0.3))
    _enable(client, superuser_token_headers, threshold=0.6)
    row = _stored(_ask_faq(client, normal_user_token_headers, db))
    assert row.intent is None


def test_service_down_does_not_break_answer(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    _fake_service(monkeypatch, down)
    _enable(client, superuser_token_headers)
    row = _stored(_ask_faq(client, normal_user_token_headers, db))
    assert row.mode == "faq"
    assert row.intent is None


def test_admin_status_and_test_endpoint(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_service(monkeypatch, _answer("obshchaga", 0.8))

    r = client.get(f"{API}/admin/intent/status", headers=normal_user_token_headers)
    assert r.status_code == 403

    status = client.get(
        f"{API}/admin/intent/status", headers=superuser_token_headers
    ).json()
    assert status["enabled"] is False
    assert status["reachable"] is True and status["model_loaded"] is True
    assert len(status["categories"]) == 24

    result = client.post(
        f"{API}/admin/intent/test",
        headers=superuser_token_headers,
        json={"question": "Где находится общага №3?"},
    ).json()
    assert result["intent"] == "obshchaga"
    assert result["intent_label"] == "Общежитие"
    assert result["candidates"][0]["label"] == "Общежитие"
