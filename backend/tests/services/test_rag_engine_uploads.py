"""Загрузка документов в Gemini File Search и AnythingLLM (httpx замокан)."""

import json

import httpx
import pytest

from app.core.config import settings
from app.services import rag_providers

STORE = "fileSearchStores/test-store"


@pytest.fixture(autouse=True)
def _engines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_FILE_SEARCH_STORE", STORE)
    monkeypatch.setattr(settings, "ANYTHINGLLM_API_KEY", "test-key")
    monkeypatch.setattr(rag_providers, "GEMINI_POLL_SECONDS", 0)


def _client(handler, **kwargs) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)


def test_gemini_list_documents_follows_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"{STORE}/documents")
        if request.url.params.get("pageToken") == "p2":
            return httpx.Response(
                200,
                json={"documents": [{"displayName": "b.pdf", "state": "STATE_ACTIVE"}]},
            )
        return httpx.Response(
            200,
            json={
                "documents": [
                    {"displayName": "a.pdf", "state": "STATE_ACTIVE", "sizeBytes": "10"}
                ],
                "nextPageToken": "p2",
            },
        )

    docs = rag_providers.list_gemini_documents(_client(handler))
    assert [(d.name, d.state, d.size_bytes) for d in docs] == [
        ("a.pdf", "ACTIVE", 10),
        ("b.pdf", "ACTIVE", None),
    ]


def test_gemini_upload_resumable_and_waits_for_operation() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith(":uploadToFileSearchStore"):
            assert request.url.path.startswith("/upload/v1beta/")
            assert request.headers["X-Goog-Upload-Command"] == "start"
            assert request.headers["X-Goog-Upload-Header-Content-Length"] == "3"
            assert json.loads(request.content)["displayName"] == "new.pdf"
            return httpx.Response(
                200, headers={"x-goog-upload-url": "https://upload.test/session/1"}
            )
        if request.url.host == "upload.test":
            assert request.headers["X-Goog-Upload-Command"] == "upload, finalize"
            assert request.content == b"pdf"
            return httpx.Response(200, json={"name": f"{STORE}/operations/op1"})
        assert request.url.path.endswith("operations/op1")
        return httpx.Response(200, json={"name": "op1", "done": True})

    status = rag_providers.upload_gemini_document(
        "new.pdf", b"pdf", "application/pdf", existing=set(), client=_client(handler)
    )
    assert status == "ok"
    assert len(calls) == 3


def test_gemini_upload_skips_existing_and_reports_operation_error() -> None:
    def never(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert (
        rag_providers.upload_gemini_document(
            "a.pdf", b"x", "application/pdf", existing={"a.pdf"}, client=_client(never)
        )
        == "already"
    )

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":uploadToFileSearchStore"):
            return httpx.Response(
                200, headers={"x-goog-upload-url": "https://u.test/s"}
            )
        return httpx.Response(
            200, json={"name": "op", "done": True, "error": {"message": "bad pdf"}}
        )

    with pytest.raises(RuntimeError, match="bad pdf"):
        rag_providers.upload_gemini_document(
            "b.pdf", b"x", "application/pdf", existing=set(), client=_client(failing)
        )


def _anything_client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return _client(handler, base_url="http://anythingllm.test/api/v1")


def test_anythingllm_upload_embeds_document() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/document/upload"):
            return httpx.Response(
                200,
                json={
                    "documents": [
                        {"location": "custom-documents/a.json", "wordCount": 50}
                    ]
                },
            )
        assert request.url.path.endswith("/update-embeddings")
        assert json.loads(request.content)["adds"] == ["custom-documents/a.json"]
        return httpx.Response(200, json={})

    status = rag_providers.upload_anythingllm_document(
        "a.pdf",
        b"x",
        "application/pdf",
        existing=set(),
        client=_anything_client(handler),
    )
    assert status == "ok"
    assert len(seen) == 2


def test_anythingllm_scan_without_text_is_marked_no_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/document/upload"), (
            "no embedding for empty doc"
        )
        return httpx.Response(
            200,
            json={
                "documents": [{"location": "custom-documents/s.json", "wordCount": 0}]
            },
        )

    status = rag_providers.upload_anythingllm_document(
        "scan.pdf",
        b"x",
        "application/pdf",
        existing=set(),
        client=_anything_client(handler),
    )
    assert status == "no-text"


def test_anythingllm_lists_workspace_documents_by_title() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "workspace": [
                    {
                        "documents": [
                            {
                                "filename": "a.json",
                                "metadata": json.dumps({"title": "a.pdf"}),
                            },
                            {"filename": "b.json"},
                        ]
                    }
                ]
            },
        )

    docs = rag_providers.list_anythingllm_documents(_anything_client(handler))
    assert [d.name for d in docs] == ["a.pdf", "b.json"]


def test_provider_configuration_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    assert rag_providers.is_provider_configured("gemini_file_search")
    assert rag_providers.is_provider_configured("legacy")
    monkeypatch.setattr(settings, "ANYTHINGLLM_API_KEY", None)
    assert not rag_providers.is_provider_configured("anythingllm")
    assert rag_providers.is_external_provider_enabled("anythingllm")
    assert not rag_providers.is_external_provider_enabled("legacy")
