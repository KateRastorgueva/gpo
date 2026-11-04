"""Тесты лёгкой векторной добавки (numpy-BERT без torch)."""

import json
import uuid
from pathlib import Path

import numpy as np
import pytest
from safetensors.numpy import save_file
from tokenizers import Tokenizer, models, pre_tokenizers

from app.core.config import settings
from app.services import dense_local
from app.services import support_service as service
from app.services.support_service import RetrievalResult

HIDDEN, HEADS, LAYERS, INTER, VOCAB = 8, 2, 2, 12, 20


def _tiny_model(path: Path) -> Path:
    """Крошечная BERT-модель со случайными весами в формате Hugging Face."""

    rng = np.random.default_rng(0)

    def mat(*shape: int) -> np.ndarray:
        return (rng.standard_normal(shape) * 0.2).astype(np.float32)

    w = {
        "embeddings.word_embeddings.weight": mat(VOCAB, HIDDEN),
        "embeddings.position_embeddings.weight": mat(32, HIDDEN),
        "embeddings.token_type_embeddings.weight": mat(2, HIDDEN),
        "embeddings.LayerNorm.weight": np.ones(HIDDEN, np.float32),
        "embeddings.LayerNorm.bias": np.zeros(HIDDEN, np.float32),
    }
    for i in range(LAYERS):
        p = f"encoder.layer.{i}"
        for name in ("query", "key", "value"):
            w[f"{p}.attention.self.{name}.weight"] = mat(HIDDEN, HIDDEN)
            w[f"{p}.attention.self.{name}.bias"] = mat(HIDDEN)
        w[f"{p}.attention.output.dense.weight"] = mat(HIDDEN, HIDDEN)
        w[f"{p}.attention.output.dense.bias"] = mat(HIDDEN)
        w[f"{p}.intermediate.dense.weight"] = mat(INTER, HIDDEN)
        w[f"{p}.intermediate.dense.bias"] = mat(INTER)
        w[f"{p}.output.dense.weight"] = mat(HIDDEN, INTER)
        w[f"{p}.output.dense.bias"] = mat(HIDDEN)
        for ln in ("attention.output.LayerNorm", "output.LayerNorm"):
            w[f"{p}.{ln}.weight"] = np.ones(HIDDEN, np.float32)
            w[f"{p}.{ln}.bias"] = np.zeros(HIDDEN, np.float32)
    path.mkdir(parents=True)
    save_file(w, str(path / "model.safetensors"))
    (path / "config.json").write_text(
        json.dumps(
            {
                "model_type": "bert",
                "hidden_size": HIDDEN,
                "num_attention_heads": HEADS,
                "num_hidden_layers": LAYERS,
                "max_position_embeddings": 32,
            }
        )
    )
    words = ["[UNK]", "[PAD]"] + [f"w{i}" for i in range(VOCAB - 2)]
    tok = Tokenizer(models.WordLevel({t: i for i, t in enumerate(words)}, "[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.save(str(path / "tokenizer.json"))
    return path


@pytest.fixture
def encoder(tmp_path: Path) -> dense_local.BertEncoder:
    return dense_local.BertEncoder(_tiny_model(tmp_path / "m"), max_tokens=16)


def test_erf_matches_math_erf() -> None:
    import math

    x = np.linspace(-4, 4, 201, dtype=np.float32)
    expected = np.array([math.erf(float(v)) for v in x])
    assert np.max(np.abs(dense_local._erf(x) - expected)) < 1e-5


def test_encoder_returns_unit_vectors_and_ignores_padding(
    encoder: dense_local.BertEncoder,
) -> None:
    short = encoder.encode(["w1 w2"])
    mixed = encoder.encode(["w1 w2", "w3 w4 w5 w6 w7 w8"])
    assert short.shape == (1, HIDDEN)
    assert np.allclose(np.linalg.norm(mixed, axis=1), 1.0, atol=1e-5)
    # Паддинг в пачке не должен менять вектор короткого текста.
    assert np.allclose(short[0], mixed[0], atol=1e-5)


def test_encoder_keeps_input_order(encoder: dense_local.BertEncoder) -> None:
    texts = ["w1 w2 w3 w4 w5", "w6", "w7 w8 w9"]
    batch = encoder.encode(texts)
    for i, text in enumerate(texts):
        assert np.allclose(batch[i], encoder.encode([text])[0], atol=1e-5)


def test_cache_persists_and_prunes(tmp_path: Path) -> None:
    cache = dense_local.DenseCache(tmp_path, "t", 3)
    vecs = np.eye(3, dtype=np.float32)
    cache.add(["a", "b", "c"], vecs)
    again = dense_local.DenseCache(tmp_path, "t", 3)  # другой воркер читает файл
    matrix, missing = again.lookup(["b", "x", "a"])
    assert missing == [1]
    assert np.allclose(matrix[0], vecs[1]) and np.allclose(matrix[2], vecs[0])
    again.add([], np.zeros((0, 3), np.float32), keep={"a"})
    assert cache.size() == 1


def test_calibrated_score_is_linear_between_floor_and_ceil() -> None:
    floor, ceil = settings.DENSE_SCORE_FLOOR, settings.DENSE_SCORE_CEIL
    assert dense_local.calibrated_score(floor - 0.1) == 0.0
    assert dense_local.calibrated_score(ceil + 0.1) == 1.0
    assert dense_local.calibrated_score((floor + ceil) / 2) == pytest.approx(0.5)


def test_search_embeds_missing_and_ranks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _tiny_model(tmp_path / "model")
    monkeypatch.setattr(dense_local, "model_dir", lambda: model)
    monkeypatch.setattr(dense_local, "_encoder", None)
    monkeypatch.setattr(dense_local, "_encoder_error", None)
    monkeypatch.setattr(dense_local, "_cache", None)
    monkeypatch.setattr(settings, "DENSE_CACHE_DIR", str(tmp_path / "cache"))
    docs = [("k1", "w1 w2 w3"), ("k2", "w4 w5 w6"), ("k3", "w1 w2 w9")]
    ranked, missing = dense_local.search("w1 w2 w3", docs)
    assert missing == 0
    assert [pos for pos, _ in ranked][0] == 0  # документ, совпадающий с запросом
    assert len(ranked) == 3
    assert dense_local.get_cache().size() == 3  # type: ignore[union-attr]


def test_rrf_uses_dense_score_when_bm25_coverage_is_low() -> None:
    chunk = uuid.uuid4()
    hit = RetrievalResult(
        source_id=uuid.uuid4(),
        source_title="Приказ о стоимости",
        source_ref=None,
        chunk_id=chunk,
        snippet="Стоимость обучения",
        score=0.0,
    )
    merged = service._rrf_merge([hit], [hit], {chunk: 0.2}, {chunk: 0.9})
    assert merged[0].score == pytest.approx(0.9)
    merged = service._rrf_merge([hit], [hit], {chunk: 0.2}, None)
    assert merged[0].score == pytest.approx(0.2)
