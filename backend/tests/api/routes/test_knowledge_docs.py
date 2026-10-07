"""Документы (независимый корпус) и фильтрация поиска по корпусу, категории и тэгам (D4)."""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import (
    DocTag,
    KnowledgeCategory,
    KnowledgeChunk,
    KnowledgeDoc,
    KnowledgeSource,
    KnowledgeTag,
    Tag,
)
from app.services.support_service import (
    build_qdrant_filter,
    retrieve_lexical_chunks,
)

KEYWORD = "гидроусилитель"


def _make_source(
    db: Session, *, keyword: str = KEYWORD, active: bool = True
) -> KnowledgeSource:
    source = KnowledgeSource(
        title=f"Источник {keyword} {uuid.uuid4().hex[:6]}",
        source_type="manual",
        content=f"Текст про {keyword} в источнике.",
        status="indexed",
        is_active=active,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    db.add(
        KnowledgeChunk(
            source_id=source.id,
            chunk_index=0,
            content=f"Подробности про {keyword}.",
            vector_id=uuid.uuid4().hex,
        )
    )
    db.commit()
    return source


def _make_doc(db: Session, *, keyword: str = KEYWORD) -> KnowledgeDoc:
    doc = KnowledgeDoc(
        title=f"Документ {keyword} {uuid.uuid4().hex[:6]}",
        url=f"https://example.edu/{uuid.uuid4().hex[:8]}",
        status="indexed",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    db.add(
        KnowledgeChunk(
            doc_id=doc.id,
            chunk_index=0,
            content=f"Инструкция про {keyword}.",
            vector_id=uuid.uuid4().hex,
        )
    )
    db.commit()
    return doc


def _make_category(db: Session, name: str) -> KnowledgeCategory:
    category = KnowledgeCategory(name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def _make_tag(db: Session, name: str) -> Tag:
    tag = Tag(name=name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def test_lexical_search_filters_by_owner_category_and_tags(db: Session) -> None:
    keyword = f"гидроусилитель{uuid.uuid4().hex[:6]}"
    category_a = _make_category(db, f"Категория A {uuid.uuid4()}")
    category_b = _make_category(db, f"Категория B {uuid.uuid4()}")
    tag_alpha = _make_tag(db, f"alpha-{uuid.uuid4().hex[:8]}")
    tag_beta = _make_tag(db, f"beta-{uuid.uuid4().hex[:8]}")

    source_a = _make_source(db, keyword=keyword)
    source_a.category_id = category_a.id
    db.add(source_a)
    db.add(KnowledgeTag(knowledge_id=source_a.id, tag_id=tag_alpha.id))

    source_b = _make_source(db, keyword=keyword)
    source_b.category_id = category_b.id
    db.add(source_b)
    db.add(KnowledgeTag(knowledge_id=source_b.id, tag_id=tag_beta.id))

    doc_d = _make_doc(db, keyword=keyword)
    db.add(DocTag(doc_id=doc_d.id, tag_id=tag_beta.id))

    inactive = _make_source(db, keyword=keyword, active=False)
    db.commit()

    def ids(**kwargs: object) -> set[uuid.UUID]:
        db.expire_all()
        results = retrieve_lexical_chunks(db, keyword, **kwargs)  # type: ignore[arg-type]
        return {item.source_id for item in results}

    # По умолчанию: оба корпуса, но неактивный источник исключён
    default_ids = ids()
    assert {source_a.id, source_b.id, doc_d.id}.issubset(default_ids)
    assert inactive.id not in default_ids

    # Корпус
    assert ids(owner_types=["source"]) == {source_a.id, source_b.id}
    assert ids(owner_types=["doc"]) == {doc_d.id}

    # Категория
    assert ids(category_ids=[category_a.id]) == {source_a.id}

    # Тэги: у источника B и документа D общий тэг
    assert ids(tag_ids=[tag_beta.id]) == {source_b.id, doc_d.id}


def test_qdrant_filter_builder() -> None:
    assert build_qdrant_filter() is None

    owner = uuid.uuid4()
    tag = uuid.uuid4()
    built = build_qdrant_filter(
        owner_types=["doc"], category_ids=[owner], tag_ids=[tag]
    )
    assert built is not None
    assert built["must"] == [
        {"key": "owner_type", "match": {"any": ["doc"]}},
        {"key": "category_id", "match": {"any": [str(owner)]}},
        {"key": "tag_ids", "match": {"any": [str(tag)]}},
    ]


def test_search_endpoint_forwards_filters(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    keyword = f"гидроусилитель{uuid.uuid4().hex[:6]}"
    source = _make_source(db, keyword=keyword)

    with patch(
        "app.services.support_service.retrieve_semantic_chunks", return_value=[]
    ) as semantic:
        response = client.post(
            f"{settings.API_V1_STR}/admin/knowledge/search",
            json={"question": keyword, "owner_types": ["source"], "limit": 5},
            headers=superuser_token_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    assert any(item["source_id"] == str(source.id) for item in body["data"])
    # Фильтр уходит и в векторный слой (Qdrant), а не только в лексический
    assert semantic.call_args.kwargs["owner_types"] == ["source"]


def test_document_crud_and_tags(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    # Создание индексирует документ; на время теста индексация подменяется
    with patch("app.api.routes.admin_support.index_doc") as index_mock:
        created = client.post(
            f"{settings.API_V1_STR}/admin/docs",
            json={
                "title": "Правовой документ",
                "url": "https://example.edu/legal",
                "tags": ["  Правовой ", "правовой"],
            },
            headers=superuser_token_headers,
        )
    assert created.status_code == 200
    assert index_mock.called
    doc_body = created.json()
    doc_id = doc_body["id"]
    assert doc_body["tags"] == ["правовой"]

    listing = client.get(
        f"{settings.API_V1_STR}/admin/docs", headers=superuser_token_headers
    )
    assert listing.status_code == 200
    assert any(item["id"] == doc_id for item in listing.json()["data"])

    updated = client.patch(
        f"{settings.API_V1_STR}/admin/docs/{doc_id}",
        json={"title": "Обновлённый документ", "tags": []},
        headers=superuser_token_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Обновлённый документ"
    assert updated.json()["tags"] == []

    deleted = client.delete(
        f"{settings.API_V1_STR}/admin/docs/{doc_id}", headers=superuser_token_headers
    )
    assert deleted.status_code == 200

    missing = client.delete(
        f"{settings.API_V1_STR}/admin/docs/{doc_id}", headers=superuser_token_headers
    )
    assert missing.status_code == 404


def test_documents_hidden_from_regular_user(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    assert (
        client.get(
            f"{settings.API_V1_STR}/admin/docs", headers=normal_user_token_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{settings.API_V1_STR}/admin/knowledge/search",
            json={"question": "расписание"},
            headers=normal_user_token_headers,
        ).status_code
        == 403
    )
