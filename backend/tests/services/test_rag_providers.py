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


def test_anythingllm_payload_uses_fresh_session_per_question() -> None:
    first = rag_providers.anythingllm_chat_payload("Вопрос")
    second = rag_providers.anythingllm_chat_payload("Вопрос")
    assert first["message"] == "Вопрос"
    assert first["mode"] == "query"
    assert first["sessionId"].startswith("support-")
    assert first["sessionId"] != second["sessionId"]


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


def _anything(answer: str, text: str, title: str = "721.pdf") -> dict:  # type: ignore[type-arg]
    return {
        "textResponse": answer,
        "sources": [{"title": title, "text": text, "score": 0.7}],
    }


def test_document_metadata_is_stripped_from_snippets() -> None:
    text = (
        "<document_metadata>\nsourceDocument: 721.pdf\npublished: 2026\n"
        "</document_metadata>\n\nСтипендия 1200 рублей."
    )
    result = rag_providers.parse_anythingllm_response(
        _anything("Стипендия 1200 рублей.", text)
    )
    assert result.sources[0].snippet == "Стипендия 1200 рублей."
    assert "document_metadata" not in (result.sources[0].text or "")


def test_unknown_document_in_answer_is_marked_and_confidence_lowered() -> None:
    result = rag_providers.parse_anythingllm_response(
        _anything(
            "Из документа Pravila_02.11.2017_(1) (1).pdf: выплата положена.",
            "Выплата положена.",
        )
    )
    assert "(источник не подтверждён)" in result.answer
    assert "Pravila_02.11.2017_(1) (1).pdf" in result.answer
    assert result.confidence == 0.35


def test_known_document_and_numbers_in_chunks_are_not_flagged() -> None:
    result = rag_providers.parse_anythingllm_response(
        _anything(
            "Согласно 721.pdf, стипендия 1 200 рублей.",
            "Размер стипендии составляет 1200 рублей.",
        )
    )
    assert "не подтверждён" not in result.answer
    assert "⚠" not in result.answer
    assert result.confidence == 0.7


def test_number_missing_in_chunks_is_marked_unverified() -> None:
    result = rag_providers.parse_anythingllm_response(
        _anything("Стипендия 1200 рублей.", "Стипендия назначается по итогам сессии.")
    )
    assert "1200" in result.answer.split("⚠")[1]
    assert result.confidence == 0.49
