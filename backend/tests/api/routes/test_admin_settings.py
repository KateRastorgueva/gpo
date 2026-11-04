"""Настройки в админке: БД вместо .env, шифрование ключей, YAML."""

from collections.abc import Iterator

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine
from app.models import AppSetting
from app.services import app_config, rag_providers
from app.services.app_config import live_settings

API = f"{settings.API_V1_STR}/admin/settings"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "ANYTHINGLLM_API_KEY", None)
    yield
    with Session(engine) as session:
        session.execute(delete(AppSetting))
        session.commit()
    app_config.invalidate_cache()


def _field(payload: dict, key: str) -> dict:  # type: ignore[type-arg]
    for group in payload["groups"]:
        for field in group["fields"]:
            if field["key"] == key:
                return field  # type: ignore[no-any-return]
    raise AssertionError(key)


def test_only_settings_manager_can_read(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(API, headers=normal_user_token_headers)
    assert r.status_code == 403


def test_override_applies_without_restart_and_reset_returns_env(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    env_workspace = settings.ANYTHINGLLM_WORKSPACE
    r = client.put(
        API,
        headers=superuser_token_headers,
        json={"values": {"ANYTHINGLLM_WORKSPACE": "tusur-2", "RETRIEVAL_TOP_K": "7"}},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["changed"]) == {"ANYTHINGLLM_WORKSPACE", "RETRIEVAL_TOP_K"}
    field = _field(r.json(), "ANYTHINGLLM_WORKSPACE")
    assert field["value"] == "tusur-2"
    assert field["default"] == env_workspace
    assert field["overridden"] is True
    assert live_settings.ANYTHINGLLM_WORKSPACE == "tusur-2"
    assert live_settings.RETRIEVAL_TOP_K == 7

    r = client.put(
        API, headers=superuser_token_headers, json={"reset": ["ANYTHINGLLM_WORKSPACE"]}
    )
    assert _field(r.json(), "ANYTHINGLLM_WORKSPACE")["overridden"] is False
    assert live_settings.ANYTHINGLLM_WORKSPACE == env_workspace


def test_invalid_values_change_nothing(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.put(
        API,
        headers=superuser_token_headers,
        json={
            "values": {
                "ANYTHINGLLM_WORKSPACE": "ok",
                "FAQ_SIMILARITY_THRESHOLD": "1.5",
                "ANYTHINGLLM_BASE_URL": "anythingllm:3001",
                "RAG_PROVIDER": "deepseek",
            }
        },
    )
    assert r.status_code == 400
    errors = r.json()["detail"]["errors"]
    assert set(errors) == {
        "FAQ_SIMILARITY_THRESHOLD",
        "ANYTHINGLLM_BASE_URL",
        "RAG_PROVIDER",
    }
    assert live_settings.ANYTHINGLLM_WORKSPACE == settings.ANYTHINGLLM_WORKSPACE


def test_secret_is_encrypted_and_never_returned(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    key = "AIzaSy-test-secret-1234"
    r = client.put(
        API, headers=superuser_token_headers, json={"values": {"GOOGLE_API_KEY": key}}
    )
    assert r.status_code == 200
    assert key not in r.text
    field = _field(r.json(), "GOOGLE_API_KEY")
    assert field["is_set"] is True
    assert field["hint"] == "…1234"
    assert field["source"] == "admin"

    db.expire_all()
    row = db.get(AppSetting, "cfg:GOOGLE_API_KEY")
    assert row is not None
    assert row.value.startswith("enc:")
    assert key not in row.value
    assert live_settings.gemini_api_key == key

    # None — «не трогать»: сохранение формы без ввода ключа его не стирает.
    client.put(
        API, headers=superuser_token_headers, json={"values": {"GOOGLE_API_KEY": None}}
    )
    assert live_settings.gemini_api_key == key


def test_secret_from_other_secret_key_is_reported(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.put(
        API,
        headers=superuser_token_headers,
        json={"values": {"ANYTHINGLLM_API_KEY": "secret-value-9999"}},
    )
    monkeypatch.setattr(settings, "SECRET_KEY", "another-secret-key")
    app_config.invalidate_cache()
    assert live_settings.ANYTHINGLLM_API_KEY is None
    # Токен админа подписан старым SECRET_KEY, поэтому смотрим форму напрямую.
    with Session(engine) as session:
        field = _field({"groups": app_config.describe(session)}, "ANYTHINGLLM_API_KEY")
    assert field["error"]
    assert field["is_set"] is False


def test_engine_becomes_configured_from_admin_key(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    assert not rag_providers.is_provider_configured("anythingllm")
    client.put(
        API,
        headers=superuser_token_headers,
        json={"values": {"ANYTHINGLLM_API_KEY": "key-from-admin"}},
    )
    assert rag_providers.is_provider_configured("anythingllm")
    r = client.put(
        f"{settings.API_V1_STR}/admin/rag/provider",
        headers=superuser_token_headers,
        json={"provider": "anythingllm"},
    )
    assert r.status_code == 200
    # Переключатель «Движки RAG» и поле «Активный движок» — одна и та же строка.
    field = _field(
        client.get(API, headers=superuser_token_headers).json(), "RAG_PROVIDER"
    )
    assert field["value"] == "anythingllm"


def test_yaml_roundtrip_without_secrets(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    client.put(
        API,
        headers=superuser_token_headers,
        json={
            "values": {
                "GOOGLE_API_KEY": "AIzaSy-must-not-leak",
                "GEMINI_FILE_SEARCH_TOP_K": 12,
            }
        },
    )
    r = client.get(f"{API}/export", headers=superuser_token_headers)
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert "must-not-leak" not in r.text
    blocks = yaml.safe_load(r.text)
    gemini = next(b for b in blocks if b["id"] == "gemini")
    assert gemini["name"] == "@ksup/rag-gemini"
    assert gemini["config"]["topK"] == 12
    assert gemini["config"]["apiKey"] is None

    # Правим выгрузку и загружаем обратно; лишнее пропускается, а не роняет импорт.
    gemini["config"]["topK"] = 3
    gemini["config"]["apiKey"] = "AIzaSy-new-key-5678"
    blocks.append({"id": "deepseek", "config": {"model": "x"}})
    next(b for b in blocks if b["id"] == "llm")["config"]["unknown"] = 1
    text = yaml.safe_dump(blocks, allow_unicode=True)
    r = client.post(
        f"{API}/import", headers=superuser_token_headers, json={"yaml": text}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "GEMINI_FILE_SEARCH_TOP_K" in body["applied"]
    assert "GOOGLE_API_KEY" in body["applied"]
    assert set(body["ignored"]) == {"deepseek", "llm.unknown"}
    # Значения, равные .env, не становятся переопределениями.
    assert "OLLAMA_MODEL" not in body["applied"]
    assert live_settings.GEMINI_FILE_SEARCH_TOP_K == 3
    assert live_settings.gemini_api_key == "AIzaSy-new-key-5678"


def test_import_rejects_broken_yaml(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    for text in (
        "- id: [",
        "just: a mapping",
        "- id: routing\n  config:\n    faqSimilarity: abc",
    ):
        r = client.post(
            f"{API}/import", headers=superuser_token_headers, json={"yaml": text}
        )
        assert r.status_code == 400, text


def test_bool_and_registry_default(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = app_config.SettingSpec(
        "EXAMPLE_FEATURE_ENABLED",
        "routing",
        "exampleEnabled",
        "Пример",
        "bool",
        default=False,
    )
    monkeypatch.setattr(app_config, "SPECS", (*app_config.SPECS, spec))
    monkeypatch.setitem(app_config.SPECS_BY_KEY, spec.key, spec)
    monkeypatch.setitem(app_config._SPECS_BY_STORAGE, spec.storage_key, spec)
    assert live_settings.EXAMPLE_FEATURE_ENABLED is False
    with Session(engine) as session:
        app_config.apply_changes(session, values={"EXAMPLE_FEATURE_ENABLED": "да"})
    assert live_settings.EXAMPLE_FEATURE_ENABLED is True
    with pytest.raises(ValueError):
        app_config.parse_value(spec, "maybe")
