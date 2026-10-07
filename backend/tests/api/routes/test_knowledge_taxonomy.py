"""Таксономия базы знаний: категории, тэги, назначение источнику, права доступа."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.permissions import ROLE_OPERATOR
from app.models import KnowledgeSource, UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _create_source(db: Session, title: str) -> KnowledgeSource:
    """Источник создаётся напрямую в БД: тесты таксономии не должны зависеть от Qdrant."""
    source = KnowledgeSource(
        title=title,
        source_type="manual",
        content="Содержимое источника для проверки таксономии.",
        status="pending",
        is_active=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def test_category_assignment_and_delete_keeps_source(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    name = f"Категория {uuid.uuid4()}"
    create = client.post(
        f"{settings.API_V1_STR}/admin/categories",
        json={"name": name},
        headers=superuser_token_headers,
    )
    assert create.status_code == 200
    category_id = create.json()["id"]

    # Дубликат в другом регистре отклоняется
    duplicate = client.post(
        f"{settings.API_V1_STR}/admin/categories",
        json={"name": name.upper()},
        headers=superuser_token_headers,
    )
    assert duplicate.status_code == 409

    listing = client.get(
        f"{settings.API_V1_STR}/admin/categories", headers=superuser_token_headers
    )
    assert listing.status_code == 200
    assert any(item["id"] == category_id for item in listing.json()["data"])

    source = _create_source(db, f"Источник {uuid.uuid4()}")
    patch = client.patch(
        f"{settings.API_V1_STR}/admin/sources/{source.id}",
        json={
            "category_id": category_id,
            "tags": ["  Важное ", "важное", "Экзамены"],
        },
        headers=superuser_token_headers,
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["category_id"] == category_id
    assert body["category_name"] == name
    # тэги нормализуются к нижнему регистру, дубликаты схлопываются, порядок по имени
    assert body["tags"] == ["важное", "экзамены"]

    # Список источников отдаёт таксономию без N+1
    sources = client.get(
        f"{settings.API_V1_STR}/admin/sources", headers=superuser_token_headers
    )
    assert sources.status_code == 200
    listed = next(
        item for item in sources.json()["data"] if item["id"] == str(source.id)
    )
    assert listed["category_name"] == name
    assert listed["tags"] == ["важное", "экзамены"]

    # Удаление категории не удаляет источник: FK выставлен в ON DELETE SET NULL
    delete = client.delete(
        f"{settings.API_V1_STR}/admin/categories/{category_id}",
        headers=superuser_token_headers,
    )
    assert delete.status_code == 200

    db.expire_all()
    refreshed = db.get(KnowledgeSource, source.id)
    assert refreshed is not None
    assert refreshed.category_id is None


def test_tag_crud_normalizes_names(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    raw_name = f"Тег-{uuid.uuid4().hex[:8]}"
    create = client.post(
        f"{settings.API_V1_STR}/admin/tags",
        json={"name": f"  {raw_name.upper()}  "},
        headers=superuser_token_headers,
    )
    assert create.status_code == 200
    created = create.json()
    assert created["name"] == raw_name.lower()

    duplicate = client.post(
        f"{settings.API_V1_STR}/admin/tags",
        json={"name": raw_name.lower()},
        headers=superuser_token_headers,
    )
    assert duplicate.status_code == 409

    listing = client.get(
        f"{settings.API_V1_STR}/admin/tags", headers=superuser_token_headers
    )
    assert listing.status_code == 200
    assert any(item["id"] == created["id"] for item in listing.json()["data"])

    delete = client.delete(
        f"{settings.API_V1_STR}/admin/tags/{created['id']}",
        headers=superuser_token_headers,
    )
    assert delete.status_code == 200

    missing = client.delete(
        f"{settings.API_V1_STR}/admin/tags/{created['id']}",
        headers=superuser_token_headers,
    )
    assert missing.status_code == 404


def test_source_update_validates_category(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    source = _create_source(db, f"Источник {uuid.uuid4()}")
    response = client.patch(
        f"{settings.API_V1_STR}/admin/sources/{source.id}",
        json={"category_id": str(uuid.uuid4())},
        headers=superuser_token_headers,
    )
    assert response.status_code == 400

    not_found = client.patch(
        f"{settings.API_V1_STR}/admin/sources/{uuid.uuid4()}",
        json={"title": "Новое имя"},
        headers=superuser_token_headers,
    )
    assert not_found.status_code == 404


def test_operator_reads_taxonomy_but_cannot_write(
    client: TestClient, db: Session
) -> None:
    """Проверка матрицы прав через API: operator имеет knowledge:read, но не taxonomy:write."""
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    operator_role = crud.get_role_by_name(session=db, name=ROLE_OPERATOR)
    assert operator_role is not None
    crud.assign_role(session=db, user=user, role=operator_role)
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )

    assert (
        client.get(
            f"{settings.API_V1_STR}/admin/categories", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.get(f"{settings.API_V1_STR}/admin/tags", headers=headers).status_code
        == 200
    )
    assert (
        client.post(
            f"{settings.API_V1_STR}/admin/categories",
            json={"name": f"Категория {uuid.uuid4()}"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{settings.API_V1_STR}/admin/tags",
            json={"name": f"tag-{uuid.uuid4().hex[:8]}"},
            headers=headers,
        ).status_code
        == 403
    )


def test_taxonomy_hidden_from_regular_user(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    assert (
        client.get(
            f"{settings.API_V1_STR}/admin/categories",
            headers=normal_user_token_headers,
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"{settings.API_V1_STR}/admin/tags", headers=normal_user_token_headers
        ).status_code
        == 403
    )
