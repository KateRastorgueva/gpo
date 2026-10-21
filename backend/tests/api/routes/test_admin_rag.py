"""Админка внешних RAG-движков: переключатель и пакетная загрузка с прогрессом."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine
from app.models import AppSetting
from app.services import rag_ingest, rag_providers

API = f"{settings.API_V1_STR}/admin/rag"


@pytest.fixture(autouse=True)
def _engines(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[None]:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_FILE_SEARCH_STORE", "fileSearchStores/t")
    monkeypatch.setattr(settings, "ANYTHINGLLM_API_KEY", "test-key")
    monkeypatch.setattr(rag_ingest, "INGEST_DIR", tmp_path)
    yield
    # Выбранный движок хранится в БД: без сброса тесты чата дальше пошли бы во
    # внешний движок вместо встроенного поиска.
    with Session(engine) as session:
        session.execute(delete(AppSetting))
        session.commit()


def test_provider_toggle_is_persisted(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    r = client.put(
        f"{API}/provider",
        headers=superuser_token_headers,
        json={"provider": "anythingllm"},
    )
    assert r.status_code == 200
    assert r.json()["active"] == "anythingllm"
    assert rag_providers.get_active_provider(db) == "anythingllm"

    r = client.put(
        f"{API}/provider",
        headers=superuser_token_headers,
        json={"provider": "gemini_file_search"},
    )
    assert r.json()["active"] == "gemini_file_search"
    names = {o["name"] for o in r.json()["options"]}
    assert names == {"gemini_file_search", "anythingllm", "legacy"}


def test_provider_toggle_requires_admin(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.put(
        f"{API}/provider",
        headers=normal_user_token_headers,
        json={"provider": "legacy"},
    )
    assert r.status_code == 403


def test_unconfigured_provider_is_rejected(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ANYTHINGLLM_API_KEY", None)
    r = client.put(
        f"{API}/provider",
        headers=superuser_token_headers,
        json={"provider": "anythingllm"},
    )
    assert r.status_code == 400


def test_ingest_job_processes_files_and_reports_progress(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{API}/ingest/jobs",
        headers=superuser_token_headers,
        json={"target": "both", "total": 2},
    )
    assert r.status_code == 200
    job_id = r.json()["id"]

    def gemini(filename: str, _data: bytes, _mime: str) -> str:
        return "already" if filename == "old.pdf" else "ok"

    def anything(filename: str, _data: bytes, _mime: str) -> str:
        if filename == "scan.pdf":
            raise RuntimeError("engine down")
        return "no-text"

    with (
        patch.object(rag_providers, "upload_gemini_document", side_effect=gemini),
        patch.object(
            rag_providers, "upload_anythingllm_document", side_effect=anything
        ),
    ):
        for name in ("old.pdf", "scan.pdf"):
            r = client.post(
                f"{API}/ingest/jobs/{job_id}/files",
                headers=superuser_token_headers,
                files={"file": (name, b"%PDF-1.4 test", "application/pdf")},
            )
            assert r.status_code == 200

    # TestClient выполняет фоновые задачи до возврата ответа.
    job = client.get(
        f"{API}/ingest/jobs/{job_id}", headers=superuser_token_headers
    ).json()
    assert job["finished"] is True
    assert (job["done"], job["failed"], job["uploaded"]) == (1, 1, 2)
    items = {i["filename"]: i for i in job["items"]}
    assert items["old.pdf"]["gemini_status"] == "already"
    assert items["old.pdf"]["anythingllm_status"] == "no-text"
    assert items["scan.pdf"]["status"] == "failed"
    assert "engine down" in items["scan.pdf"]["error"]

    r = client.post(
        f"{API}/ingest/jobs/{job_id}/files",
        headers=superuser_token_headers,
        files={"file": ("extra.pdf", b"x", "application/pdf")},
    )
    assert r.status_code == 409

    listed = client.get(f"{API}/ingest/jobs", headers=superuser_token_headers).json()
    assert any(j["id"] == job_id for j in listed["data"])


def test_engine_documents_listing_shows_errors(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    with patch.object(
        rag_providers, "list_gemini_documents", side_effect=RuntimeError("quota")
    ):
        r = client.get(
            f"{API}/documents",
            headers=superuser_token_headers,
            params={"engine": "gemini"},
        )
    body = r.json()
    assert r.status_code == 200
    assert body["configured"] is True
    assert "quota" in body["error"]
