"""Режим «только поиск»: встроенный BM25 без Qdrant и без LLM."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.core.db import engine
from app.models import AppSetting, KnowledgeChunk, KnowledgeSource
from app.services import rag_ingest
from app.services import support_service as service

API = settings.API_V1_STR
DOC_NAME = "test_obshchezhitie_search_only.txt"
DOC_TEXT = (
    "Положение о студенческом общежитии.\n"
    "Заселение в общежитие проводится по приказу ректора. "
    "Плата за проживание в общежитии вносится ежемесячно до 10 числа "
    "через личный кабинет студента или в кассе университета. "
    "При задолженности более двух месяцев договор найма может быть расторгнут.\n"
    "Гостевой пропуск оформляется у коменданта."
)


@pytest.fixture(autouse=True)
def _cleanup(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(rag_ingest, "INGEST_DIR", tmp_path)
    yield
    with Session(engine) as session:
        ids = session.exec(
            select(KnowledgeSource.id).where(KnowledgeSource.source_ref == DOC_NAME)
        ).all()
        session.execute(
            delete(KnowledgeChunk).where(col(KnowledgeChunk.source_id).in_(ids))
        )
        session.execute(delete(KnowledgeSource).where(col(KnowledgeSource.id).in_(ids)))
        session.execute(delete(AppSetting))
        session.commit()


def _no_qdrant(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("Qdrant must not be called when vector search is off")


def _no_llm(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("LLM must not be called in search_only mode")


def _upload_local(client: TestClient, headers: dict[str, str]) -> dict:  # type: ignore[type-arg]
    r = client.post(
        f"{API}/admin/rag/ingest/jobs",
        headers=headers,
        json={"target": "local", "total": 1},
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    r = client.post(
        f"{API}/admin/rag/ingest/jobs/{job_id}/files",
        headers=headers,
        files={"file": (DOC_NAME, DOC_TEXT.encode(), "text/plain")},
    )
    assert r.status_code == 200, r.text
    return client.get(f"{API}/admin/rag/ingest/jobs/{job_id}", headers=headers).json()


def test_search_only_answers_with_fragments_without_qdrant_and_llm(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    assert service.vector_search_enabled() is False
    with (
        patch.object(service, "_qdrant_request", side_effect=_no_qdrant),
        patch.object(service, "embed_texts", side_effect=_no_qdrant),
        patch.object(service, "generate_answer", side_effect=_no_llm),
        patch.object(service, "find_faq_match", return_value=(None, 0.0)),
    ):
        job = _upload_local(client, superuser_token_headers)
        assert job["finished"] is True and job["done"] == 1, job
        assert job["items"][0]["local_status"] == "ok"

        r = client.put(
            f"{API}/admin/rag/provider",
            headers=superuser_token_headers,
            json={"provider": "search_only"},
        )
        assert r.status_code == 200 and r.json()["active"] == "search_only"

        r = client.post(
            f"{API}/support/ask",
            headers=normal_user_token_headers,
            json={
                "question": "Как оплачивать проживание в общежитии?",
                "channel": "web",
            },
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "rag"
    assert body["route_reason"] == "search_only"
    assert body["escalated"] is False
    assert body["fallback_used"] is False
    assert "test_obshchezhitie_search_only" in body["answer"]
    assert "Плата за проживание" in body["answer"]
    assert "релевантность" in body["answer"]
    assert body["sources"][0]["source_ref"] == DOC_NAME


def test_local_upload_replaces_file_with_same_name(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    with patch.object(service, "_qdrant_request", side_effect=_no_qdrant):
        _upload_local(client, superuser_token_headers)
        _upload_local(client, superuser_token_headers)
    with Session(engine) as session:
        sources = session.exec(
            select(KnowledgeSource).where(KnowledgeSource.source_ref == DOC_NAME)
        ).all()
    assert len(sources) == 1
    assert sources[0].status == "indexed"


def test_search_only_still_escalates_without_context(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    client.put(
        f"{API}/admin/rag/provider",
        headers=superuser_token_headers,
        json={"provider": "search_only"},
    )
    with (
        patch.object(service, "find_faq_match", return_value=(None, 0.0)),
        patch.object(service, "retrieve_relevant_chunks", return_value=[]),
        patch.object(service, "generate_answer", side_effect=_no_llm),
    ):
        r = client.post(
            f"{API}/support/ask",
            headers=normal_user_token_headers,
            json={"question": "Какая погода на Марсе?", "channel": "web"},
        )
    body = r.json()
    assert body["mode"] == "operator"
    assert body["escalated"] is True


def test_best_fragment_picks_sentence_with_question_words() -> None:
    fragment = service.best_fragment(
        "Где оформить гостевой пропуск?", DOC_TEXT, limit=120
    )
    assert "Гостевой пропуск" in fragment
    assert "Заселение" not in fragment
    assert len(fragment) <= 125
