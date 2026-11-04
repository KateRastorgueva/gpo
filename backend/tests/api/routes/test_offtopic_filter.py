"""Фильтр офтопа в /support/ask и кнопка «Передать оператору» (/support/escalate)."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, func, select

from app.core.config import settings
from app.core.db import engine
from app.models import AppSetting, SupportRequest, SupportTicket
from app.services import app_config, offtopic
from app.services import support_service as service
from app.services.support_service import RetrievalResult

API = settings.API_V1_STR


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    with Session(engine) as session:
        session.execute(delete(AppSetting))
        session.commit()
    app_config.invalidate_cache()


def _enable(session: Session, **extra: object) -> None:
    app_config.apply_changes(session, {"OFFTOPIC_FILTER_ENABLED": True, **extra})


def _counts() -> tuple[int, int]:
    with Session(engine) as session:
        requests = session.exec(select(func.count()).select_from(SupportRequest)).one()
        tickets = session.exec(select(func.count()).select_from(SupportTicket)).one()
    return requests, tickets


def _chunk(score: float = 0.9) -> RetrievalResult:
    import uuid

    return RetrievalResult(
        source_id=uuid.uuid4(),
        source_title="Положение",
        source_ref="x.txt",
        chunk_id=uuid.uuid4(),
        snippet="текст",
        score=score,
    )


def _ask(client: TestClient, headers: dict[str, str], question: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"{API}/support/ask",
        headers=headers,
        json={"question": question, "channel": "web"},
    )


def test_filter_is_off_by_default(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    assert app_config.live_settings.OFFTOPIC_FILTER_ENABLED is False
    with (
        patch.object(service, "find_faq_match", return_value=(None, 0.0)),
        patch.object(service, "retrieve_relevant_chunks", return_value=[]),
    ):
        body = _ask(client, normal_user_token_headers, "ааааааа").json()
    assert body["mode"] == "operator"
    assert body["escalated"] is True


def test_junk_is_rejected_without_queue_record(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with Session(engine) as session:
        _enable(session)
    before = _counts()
    with (
        patch.object(service, "find_faq_match", return_value=(None, 0.0)),
        patch.object(service, "retrieve_relevant_chunks") as retrieve,
    ):
        r = _ask(client, normal_user_token_headers, "ghbdtn")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "reject"
    assert body["request_id"] is None
    assert body["escalated"] is False
    assert body["route_reason"] == offtopic.REASON_JUNK_LAYOUT
    assert "Передать оператору" in body["answer"]
    retrieve.assert_not_called()
    assert _counts() == before


def test_low_mean_similarity_is_rejected(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with Session(engine) as session:
        _enable(session)

    def fake_retrieve(**kwargs: object) -> list[RetrievalResult]:
        kwargs["diagnostics"]["dense_cosines"] = [0.28, 0.27, 0.25, 0.2, 0.1]  # type: ignore[index]
        return [_chunk()]

    before = _counts()
    with (
        patch.object(service, "find_faq_match", return_value=(None, 0.0)),
        patch.object(service, "retrieve_relevant_chunks", side_effect=fake_retrieve),
    ):
        body = _ask(client, normal_user_token_headers, "Какой рецепт борща?").json()
    assert body["mode"] == "reject"
    assert body["route_reason"] == offtopic.REASON_LOW_SIMILARITY
    assert _counts() == before


def test_on_topic_question_passes_the_filter(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with Session(engine) as session:
        _enable(session)

    def fake_retrieve(**kwargs: object) -> list[RetrievalResult]:
        kwargs["diagnostics"]["dense_cosines"] = [0.62, 0.55, 0.5, 0.45, 0.4]  # type: ignore[index]
        return [_chunk(0.95), _chunk(0.9)]

    with (
        patch.object(service, "find_faq_match", return_value=(None, 0.0)),
        patch.object(service, "retrieve_relevant_chunks", side_effect=fake_retrieve),
        patch.object(service, "generate_answer", return_value=("Ответ", False)),
    ):
        body = _ask(client, normal_user_token_headers, "Как оформить отпуск?").json()
    assert body["mode"] == "rag"
    assert body["request_id"] is not None


def test_threshold_comes_from_settings(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with Session(engine) as session:
        _enable(session, OFFTOPIC_MIN_MEAN_SIMILARITY=0.6)

    def fake_retrieve(**kwargs: object) -> list[RetrievalResult]:
        kwargs["diagnostics"]["dense_cosines"] = [0.55] * 5  # type: ignore[index]
        return [_chunk()]

    with (
        patch.object(service, "find_faq_match", return_value=(None, 0.0)),
        patch.object(service, "retrieve_relevant_chunks", side_effect=fake_retrieve),
    ):
        body = _ask(client, normal_user_token_headers, "Вопрос по учёбе").json()
    assert body["mode"] == "reject"


def test_without_dense_cosines_similarity_check_is_skipped(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with Session(engine) as session:
        _enable(session)
    with (
        patch.object(service, "find_faq_match", return_value=(None, 0.0)),
        patch.object(service, "retrieve_relevant_chunks", return_value=[]),
    ):
        body = _ask(client, normal_user_token_headers, "Какая погода на Марсе?").json()
    assert body["mode"] == "operator"


def test_escalate_creates_queue_record(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    before_requests, before_tickets = _counts()
    r = client.post(
        f"{API}/support/escalate",
        headers=normal_user_token_headers,
        json={"question": "Нужен живой человек", "session_id": "s-1", "channel": "web"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "operator"
    assert body["escalated"] is True
    assert body["request_id"]
    assert body["session_id"] == "s-1"
    assert _counts() == (before_requests + 1, before_tickets + 1)
    history = client.get(
        f"{API}/support/history?session_id=s-1", headers=normal_user_token_headers
    ).json()
    assert history["count"] == 1
    assert history["data"][0]["status"] == "queued"


def test_offtopic_settings_visible_in_admin(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{API}/admin/settings", headers=superuser_token_headers)
    assert r.status_code == 200, r.text
    groups = {g["id"]: g for g in r.json()["groups"]}
    fields = {f["key"]: f for f in groups["offtopic"]["fields"]}
    assert set(fields) == {
        "OFFTOPIC_FILTER_ENABLED",
        "OFFTOPIC_MIN_MEAN_SIMILARITY",
        "OFFTOPIC_TOP_N",
    }
    assert fields["OFFTOPIC_FILTER_ENABLED"]["value"] is False
    assert fields["OFFTOPIC_MIN_MEAN_SIMILARITY"]["value"] == 0.3
