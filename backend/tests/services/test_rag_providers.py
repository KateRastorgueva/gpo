from app.services import rag_providers


def _gemini_body(text: str, supported_bytes: int, with_chunk: bool = True) -> dict:  # type: ignore[type-arg]
    metadata = {
        "groundingChunks": [
            {
                "retrievedContext": {
                    "title": "Poryadok.pdf",
                    "text": "фрагмент",
                    "pageNumber": 3,
                }
            }
        ]
        if with_chunk
        else [],
        "groundingSupports": [
            {
                "segment": {"startIndex": 0, "endIndex": supported_bytes},
                "groundingChunkIndices": [0],
            }
        ],
    }
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "groundingMetadata": metadata}
        ]
    }


def test_gemini_grounded_answer_has_sources_and_coverage() -> None:
    text = "Перевод оформляется по заявлению."
    full = len(text.encode("utf-8"))
    result = rag_providers.parse_gemini_response(_gemini_body(text, full // 2))
    assert result.grounded
    assert 0.4 < result.confidence < 0.6
    assert result.sources[0].title == "Poryadok.pdf"
    assert result.sources[0].page == 3


def test_gemini_no_answer_marker_is_not_grounded() -> None:
    result = rag_providers.parse_gemini_response(
        _gemini_body(rag_providers.NO_ANSWER_MARKER, 0, with_chunk=True)
    )
    assert not result.grounded
    assert result.confidence == 0.0


def test_gemini_answer_without_chunks_is_not_grounded() -> None:
    result = rag_providers.parse_gemini_response(
        _gemini_body("Ответ", 10, with_chunk=False)
    )
    assert not result.grounded


def test_anythingllm_refusal_is_not_grounded() -> None:
    body = {
        "textResponse": "There is no relevant information in this workspace to answer your query.",
        "sources": [],
    }
    assert not rag_providers.parse_anythingllm_response(body).grounded


def test_anythingllm_answer_uses_best_source_score() -> None:
    body = {
        "textResponse": "Ответ",
        "sources": [
            {"title": "a.pdf", "text": "t", "score": 0.71},
            {"title": "b.pdf", "score": 0.5},
        ],
    }
    result = rag_providers.parse_anythingllm_response(body)
    assert result.grounded
    assert result.confidence == 0.71
    assert [s.title for s in result.sources] == ["a.pdf", "b.pdf"]


def test_source_id_is_stable_per_title() -> None:
    a = rag_providers.ProviderSource(title="x.pdf")
    b = rag_providers.ProviderSource(title="x.pdf")
    assert a.source_id == b.source_id


def test_no_answer_marker_with_latin_letters_is_detected() -> None:
    result = rag_providers.parse_gemini_response(_gemini_body("НЕТ_OTBETА", 0))
    assert not result.grounded
