"""Архив версий знания: снапшоты при изменении, мягкое удаление, CASCADE при жёстком."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import KnowledgeArchive, KnowledgeSource


def _make_source(db: Session, *, title: str = "Источник v1") -> KnowledgeSource:
    source = KnowledgeSource(
        title=title,
        source_type="manual",
        content="Содержимое версии для проверки архива.",
        status="pending",
        is_active=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _patch_source(
    client: TestClient, headers: dict[str, str], source_id: uuid.UUID, title: str
) -> int:
    response = client.patch(
        f"{settings.API_V1_STR}/admin/sources/{source_id}",
        json={"title": title},
        headers=headers,
    )
    return response.status_code


def test_update_creates_archive_versions(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    source = _make_source(db, title="Версия 1")

    assert _patch_source(client, superuser_token_headers, source.id, "Версия 2") == 200
    assert _patch_source(client, superuser_token_headers, source.id, "Версия 3") == 200

    archive = client.get(
        f"{settings.API_V1_STR}/admin/sources/{source.id}/archive",
        headers=superuser_token_headers,
    )
    assert archive.status_code == 200
    body = archive.json()
    assert body["count"] == 2
    # Снапшот хранит состояние ДО изменения, свежие версии сверху
    assert [item["version"] for item in body["data"]] == [2, 1]
    assert [item["title"] for item in body["data"]] == ["Версия 2", "Версия 1"]
    assert body["data"][0]["archived_by"] is not None
    assert body["data"][0]["source_type"] == "manual"

    missing = client.get(
        f"{settings.API_V1_STR}/admin/sources/{uuid.uuid4()}/archive",
        headers=superuser_token_headers,
    )
    assert missing.status_code == 404


def test_deactivate_keeps_source_and_history(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    source = _make_source(db)
    source_id = source.id

    response = client.post(
        f"{settings.API_V1_STR}/admin/sources/{source_id}/deactivate",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["status"] == "deleted"

    db.expire_all()
    assert db.get(KnowledgeSource, source_id) is not None

    archive = client.get(
        f"{settings.API_V1_STR}/admin/sources/{source_id}/archive",
        headers=superuser_token_headers,
    )
    assert archive.json()["count"] == 1


def test_hard_delete_removes_archive(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    source = _make_source(db)
    source_id = source.id
    assert _patch_source(client, superuser_token_headers, source_id, "Изменено") == 200

    db.expire_all()
    archived = db.exec(
        select(KnowledgeArchive).where(KnowledgeArchive.knowledge_id == source_id)
    ).all()
    assert len(archived) == 1

    deleted = client.delete(
        f"{settings.API_V1_STR}/admin/sources/{source_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200

    # Строка источника и её история удалены (FK ON DELETE CASCADE — решение V6).
    # id берём из локальной переменной: обращение к удалённому объекту ORM недопустимо.
    db.expire_all()
    remaining = db.exec(
        select(KnowledgeArchive).where(KnowledgeArchive.knowledge_id == source_id)
    ).all()
    assert remaining == []


def test_archive_retention_keeps_last_versions(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "KNOWLEDGE_ARCHIVE_MAX_VERSIONS", 2, raising=False)
    source = _make_source(db, title="v0")
    for index in range(1, 4):
        assert (
            _patch_source(client, superuser_token_headers, source.id, f"v{index}") == 200
        )

    archive = client.get(
        f"{settings.API_V1_STR}/admin/sources/{source.id}/archive",
        headers=superuser_token_headers,
    )
    assert archive.json()["count"] == 2
    assert [item["version"] for item in archive.json()["data"]] == [3, 2]


def test_archive_hidden_from_regular_user(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    source = _make_source(db)
    assert (
        client.get(
            f"{settings.API_V1_STR}/admin/sources/{source.id}/archive",
            headers=normal_user_token_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{settings.API_V1_STR}/admin/sources/{source.id}/deactivate",
            headers=normal_user_token_headers,
        ).status_code
        == 403
    )
