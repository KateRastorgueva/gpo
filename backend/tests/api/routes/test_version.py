from fastapi.testclient import TestClient

from app.core.config import settings

URL = f"{settings.API_V1_STR}/utils/version"


def test_version_requires_login(client: TestClient) -> None:
    assert client.get(URL).status_code in (401, 403)


def test_version_unknown_without_build_args(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    for name in ("GIT_SHA", "GIT_BRANCH", "BUILD_TIME"):
        monkeypatch.delenv(name, raising=False)
    data = client.get(URL, headers=normal_user_token_headers).json()
    assert data["git_sha"] == data["git_sha_short"] == "unknown"
    assert data["git_branch"] == data["build_time"] == "unknown"
    assert isinstance(data["vector_search_enabled"], bool)
    assert isinstance(data["offtopic_filter_enabled"], bool)
    assert data["rag_provider"]


def test_version_from_build_env(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setenv("GIT_SHA", "0123456789abcdef")
    monkeypatch.setenv("GIT_BRANCH", "master")
    monkeypatch.setenv("BUILD_TIME", "2026-11-04T19:30:00Z")
    data = client.get(URL, headers=normal_user_token_headers).json()
    assert data["git_sha_short"] == "0123456"
    assert data["git_branch"] == "master"
    assert data["build_time"] == "2026-11-04T19:30:00Z"
