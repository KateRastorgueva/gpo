import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pypdf import PdfWriter

from app.core.config import settings
from app.services import support_service as service

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_embedding_backend() -> None:
    service._embedding_backend = None
    yield
    service._embedding_backend = None


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_extract_pdf_reads_cyrillic_text_layer() -> None:
    text = service._extract_text_from_pdf((FIXTURES / "sample_ru_text_layer.pdf").read_bytes())
    assert "пересдач" in text
    assert "кабинете 302" in text
    assert "\x00" not in text


def test_extract_pdf_without_text_layer_is_rejected() -> None:
    with pytest.raises(ValueError, match="no text layer"):
        service._extract_text_from_pdf(_blank_pdf())


def test_extract_pdf_rejects_non_pdf_bytes() -> None:
    with pytest.raises(ValueError, match="not a PDF"):
        service._extract_text_from_pdf(b"\x00\x01binary garbage")


def test_extract_html_detects_cp1251_and_drops_navigation() -> None:
    html = (
        "<html><body><nav>Главная | Контакты</nav><main><p>Заселение в общежитие "
        "по направлению профкома.</p></main><footer>Все права защищены</footer>"
        "<script>var a=1;</script></body></html>"
    ).encode("cp1251")
    text = service._extract_text_from_html(html, "text/html")
    assert "Заселение в общежитие" in text
    assert "Главная" not in text
    assert "Все права защищены" not in text
    assert "var a" not in text


def test_ensure_utf8_text_strips_nul_bytes() -> None:
    assert service._ensure_utf8_text(" a\x00b ") == "ab"


def test_embedding_backend_is_resolved_once_and_never_mixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMBEDDING_BACKEND", "google")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "test-key")
    with patch.object(service, "_embed_with_google", return_value=None):
        with pytest.raises(RuntimeError, match="Google embedding request failed"):
            service.embed_texts(["вопрос"])
    assert service.get_embedding_backend() == "google"


def test_hashed_backend_vectors_have_configured_dim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EMBEDDING_BACKEND", "hashed")
    vectors = service.embed_texts(["первый текст", "второй текст"])
    assert [len(vector) for vector in vectors] == [settings.EMBEDDING_DIM] * 2
    assert service.get_embedding_model_id().startswith("hashed:")


def test_routing_thresholds_depend_on_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EMBEDDING_BACKEND", "hashed")
    assert service.routing_thresholds() == (
        settings.RAG_TOP_SCORE_THRESHOLD_HASHED,
        settings.RAG_RELEVANT_CHUNK_THRESHOLD_HASHED,
        settings.RAG_MIN_RELEVANT_CHUNKS_HASHED,
    )
    service._embedding_backend = "sentence-transformers"
    assert service.routing_thresholds() == (
        settings.RAG_TOP_SCORE_THRESHOLD,
        settings.RAG_RELEVANT_CHUNK_THRESHOLD,
        settings.RAG_MIN_RELEVANT_CHUNKS,
    )


def test_ensure_collection_rejects_vector_size_mismatch() -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"result": {"config": {"params": {"vectors": {"size": 768}}}}}
    with patch.object(service, "_qdrant_request", return_value=response):
        with pytest.raises(RuntimeError, match="vector size 768"):
            service.ensure_qdrant_collection(384)
