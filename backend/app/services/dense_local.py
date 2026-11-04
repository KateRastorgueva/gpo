"""Лёгкая векторная добавка к BM25: маленькая BERT-модель в numpy, без torch.

Зачем: BM25 не находит синонимы и другие формы слова («сколько стоит» →
«стоимость обучения»). Векторный поиск их находит, но обычный стек
(sentence-transformers + torch + Qdrant) весит гигабайты. Здесь:

* модель — rubert-mini-frida (32 млн параметров, 312 измерений, ~125 МБ),
  файлы из Hugging Face лежат в каталоге ``LOCAL_EMBEDDING_MODEL_DIR``;
* прямой проход BERT написан на numpy (7 слоёв), токенизатор — ``tokenizers``;
* векторы чанков считаются один раз и хранятся в ``DENSE_CACHE_DIR`` по хэшу
  текста, поэтому переживают перезапуск и не пересчитываются без изменений;
* кэш общий для воркеров: досчитывает один процесс (файловая блокировка),
  остальные перечитывают файл, когда он обновится.

Списки BM25 и векторного поиска склеивает RRF в ``support_service``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.services.app_config import live_settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 8


class BertEncoder:
    """Кодировщик предложений (BERT + mean pooling + L2-нормировка) на numpy."""

    def __init__(self, model_dir: str | Path, max_tokens: int = 512) -> None:
        from safetensors.numpy import load_file
        from tokenizers import Tokenizer

        path = Path(model_dir)
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
        if config.get("model_type") != "bert":
            raise ValueError(f"Ожидалась BERT-модель, а не {config.get('model_type')}")
        self.hidden = int(config["hidden_size"])
        self.heads = int(config["num_attention_heads"])
        self.layers = int(config["num_hidden_layers"])
        self.eps = float(config.get("layer_norm_eps", 1e-12))
        self.max_tokens = min(max_tokens, int(config["max_position_embeddings"]))
        self.name = path.name

        weights = load_file(str(path / "model.safetensors"))
        prefix = "bert." if "bert.embeddings.word_embeddings.weight" in weights else ""
        self._w = {
            key[len(prefix) :]: value.astype(np.float32, copy=False)
            for key, value in weights.items()
            if key.startswith(prefix) and not key[len(prefix) :].startswith("pooler.")
        }
        # Матрицы Linear хранятся как (out, in): транспонируем один раз заранее.
        for key in list(self._w):
            if (
                key.endswith(".weight")
                and self._w[key].ndim == 2
                and "embeddings" not in key
            ):
                self._w[key] = np.ascontiguousarray(self._w[key].T)

        tokenizer = Tokenizer.from_file(str(path / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=self.max_tokens)
        tokenizer.no_padding()
        self._tokenizer = tokenizer
        self.dim = self.hidden

    # --- математика -----------------------------------------------------------

    def _layer_norm(self, x: np.ndarray, name: str) -> np.ndarray:
        mean = x.mean(axis=-1, keepdims=True)
        var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
        out: np.ndarray = (x - mean) / np.sqrt(var + self.eps)
        return out * self._w[f"{name}.weight"] + self._w[f"{name}.bias"]

    def _linear(self, x: np.ndarray, name: str) -> np.ndarray:
        out: np.ndarray = x @ self._w[f"{name}.weight"] + self._w[f"{name}.bias"]
        return out

    @staticmethod
    def _gelu(x: np.ndarray) -> np.ndarray:
        # Точная GELU через erf, как в transformers ("gelu").
        out: np.ndarray = 0.5 * x * (1.0 + _erf(x / math.sqrt(2.0)))
        return out

    def _forward(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        batch, length = ids.shape
        w = self._w
        x = (
            w["embeddings.word_embeddings.weight"][ids]
            + w["embeddings.position_embeddings.weight"][np.arange(length)][None, :, :]
            + w["embeddings.token_type_embeddings.weight"][0][None, None, :]
        )
        x = self._layer_norm(x, "embeddings.LayerNorm")
        head_dim = self.hidden // self.heads
        bias = (1.0 - mask[:, None, None, :].astype(np.float32)) * np.float32(-1e9)
        scale = np.float32(1.0 / math.sqrt(head_dim))
        for index in range(self.layers):
            p = f"encoder.layer.{index}"

            def split(t: np.ndarray) -> np.ndarray:
                # Непрерывная память обязательна: иначе numpy умножает пачку
                # матриц без BLAS и внимание считается в разы дольше.
                return np.ascontiguousarray(
                    t.reshape(batch, length, self.heads, head_dim).transpose(0, 2, 1, 3)
                )

            q = split(self._linear(x, f"{p}.attention.self.query") * scale)
            k = split(self._linear(x, f"{p}.attention.self.key"))
            v = split(self._linear(x, f"{p}.attention.self.value"))
            scores = np.matmul(q, np.ascontiguousarray(k.transpose(0, 1, 3, 2)))
            scores += bias
            scores -= scores.max(axis=-1, keepdims=True)
            np.exp(scores, out=scores)
            scores /= scores.sum(axis=-1, keepdims=True)
            context = np.ascontiguousarray(
                np.matmul(scores, v).transpose(0, 2, 1, 3)
            ).reshape(batch, length, self.hidden)
            attn = self._linear(context, f"{p}.attention.output.dense")
            x = self._layer_norm(attn + x, f"{p}.attention.output.LayerNorm")
            inter = self._gelu(self._linear(x, f"{p}.intermediate.dense"))
            out = self._linear(inter, f"{p}.output.dense")
            x = self._layer_norm(out + x, f"{p}.output.LayerNorm")
        return x

    def encode(self, texts: Sequence[str], prefix: str = "") -> np.ndarray:
        """Векторы текстов (float32, нормированы по L2), shape = (n, dim)."""

        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        encodings = self._tokenizer.encode_batch([prefix + t for t in texts])
        order = sorted(range(len(encodings)), key=lambda i: len(encodings[i].ids))
        result = np.zeros((len(texts), self.dim), dtype=np.float32)
        for start in range(0, len(order), _BATCH_SIZE):
            idx = order[start : start + _BATCH_SIZE]
            length = max(len(encodings[i].ids) for i in idx)
            ids = np.zeros((len(idx), length), dtype=np.int64)
            mask = np.zeros((len(idx), length), dtype=np.int64)
            for row, i in enumerate(idx):
                seq = encodings[i].ids
                ids[row, : len(seq)] = seq
                mask[row, : len(seq)] = 1
            hidden = self._forward(ids, mask)
            m = mask[:, :, None].astype(np.float32)
            pooled = (hidden * m).sum(axis=1) / np.maximum(m.sum(axis=1), 1e-9)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            result[idx] = pooled / np.maximum(norms, 1e-12)
        return result


def _erf(x: np.ndarray) -> np.ndarray:
    """erf для массивов numpy без scipy: аппроксимация erfc Чебышёва
    (Numerical Recipes, «erfcc»), относительная погрешность < 1.2e-7."""

    a = np.abs(x).astype(np.float32)
    t = 1.0 / (1.0 + 0.5 * a)
    y = 1.0 - t * np.exp(
        -a * a
        - 1.26551223
        + t
        * (
            1.00002368
            + t
            * (
                0.37409196
                + t
                * (
                    0.09678418
                    + t
                    * (
                        -0.18628806
                        + t
                        * (
                            0.27886807
                            + t
                            * (
                                -1.13520398
                                + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277))
                            )
                        )
                    )
                )
            )
        )
    )
    return np.where(x >= 0, y, -y).astype(np.float32)


# --- состояние процесса -------------------------------------------------------

_encoder: BertEncoder | None = None
_encoder_error: str | None = None
_encoder_lock = threading.Lock()


def model_dir() -> Path:
    return Path(live_settings.LOCAL_EMBEDDING_MODEL_DIR)


def model_available() -> bool:
    path = model_dir()
    return (path / "model.safetensors").is_file() and (
        path / "tokenizer.json"
    ).is_file()


def get_encoder() -> BertEncoder | None:
    """Загружает модель один раз на процесс. None — модели нет или она не читается."""

    global _encoder, _encoder_error
    if _encoder is not None:
        return _encoder
    if _encoder_error is not None or not model_available():
        return None
    with _encoder_lock:
        if _encoder is None and _encoder_error is None:
            try:
                started = time.perf_counter()
                _encoder = BertEncoder(model_dir(), settings.DENSE_MAX_TOKENS)
                logger.info(
                    "dense model %s loaded in %.1f s",
                    _encoder.name,
                    time.perf_counter() - started,
                )
            except Exception as exc:  # битые файлы не должны ронять поиск
                _encoder_error = f"{type(exc).__name__}: {exc}"
                logger.warning("dense model unavailable: %s", _encoder_error)
    return _encoder


def encoder_error() -> str | None:
    return _encoder_error


def text_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class DenseCache:
    """Векторы документов по sha1 текста; файл .npz общий для всех воркеров."""

    def __init__(self, directory: str | Path, tag: str, dim: int) -> None:
        self.dir = Path(directory)
        self.path = self.dir / f"{tag}.npz"
        self.lock_path = self.dir / f"{tag}.lock"
        self.dim = dim
        self._index: dict[str, int] = {}
        self._matrix = np.zeros((0, dim), dtype=np.float32)
        self._mtime: float | None = None
        self._lock = threading.Lock()

    def _reload_if_changed(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime == self._mtime:
            return
        try:
            with np.load(self.path, allow_pickle=False) as data:
                keys = [str(k) for k in data["keys"]]
                matrix = np.asarray(data["vectors"], dtype=np.float32)
        except Exception as exc:
            logger.warning("dense cache %s unreadable: %s", self.path, exc)
            return
        if matrix.shape != (len(keys), self.dim):
            return
        self._index = {k: i for i, k in enumerate(keys)}
        self._matrix = matrix
        self._mtime = mtime

    def lookup(self, keys: Sequence[str]) -> tuple[np.ndarray, list[int]]:
        """Матрица для keys (нули для отсутствующих) и позиции отсутствующих."""

        with self._lock:
            self._reload_if_changed()
            out = np.zeros((len(keys), self.dim), dtype=np.float32)
            missing: list[int] = []
            for pos, key in enumerate(keys):
                row = self._index.get(key)
                if row is None:
                    missing.append(pos)
                else:
                    out[pos] = self._matrix[row]
            return out, missing

    def add(
        self, keys: Sequence[str], vectors: np.ndarray, *, keep: set[str] | None = None
    ) -> None:
        """Добавляет векторы и сохраняет файл атомарно (tmp + rename).

        keep — ключи, которые нужно оставить (остальные удаляются как устаревшие).
        """

        with self._lock:
            self._reload_if_changed()
            index = dict(self._index)
            rows = [self._matrix]
            next_row = self._matrix.shape[0]
            new_rows = []
            for key, vector in zip(keys, vectors, strict=True):
                if key in index:
                    continue
                index[key] = next_row
                new_rows.append(vector)
                next_row += 1
            if new_rows:
                rows.append(np.asarray(new_rows, dtype=np.float32))
            matrix = np.concatenate(rows, axis=0) if len(rows) > 1 else self._matrix
            if keep is not None:
                kept = [k for k in index if k in keep]
                matrix = matrix[[index[k] for k in kept]] if kept else matrix[:0]
                index = {k: i for i, k in enumerate(kept)}
            if not new_rows and keep is None:
                return
            self.dir.mkdir(parents=True, exist_ok=True)
            ordered = sorted(index, key=index.__getitem__)
            tmp = self.path.with_name(f"{self.path.stem}.{os.getpid()}.tmp.npz")
            np.savez(tmp, keys=np.asarray(ordered), vectors=matrix)
            os.replace(tmp, self.path)
            self._index = {k: i for i, k in enumerate(ordered)}
            self._matrix = matrix
            self._mtime = self.path.stat().st_mtime

    def size(self) -> int:
        with self._lock:
            self._reload_if_changed()
            return len(self._index)


_cache: DenseCache | None = None


def get_cache() -> DenseCache | None:
    global _cache
    encoder = get_encoder()
    if encoder is None:
        return None
    if _cache is None:
        _cache = DenseCache(
            settings.DENSE_CACHE_DIR, f"{encoder.name}-{encoder.dim}", encoder.dim
        )
    return _cache


def document_text(title: str, content: str) -> str:
    return f"{title}\n{content}" if title else content


# --- фоновое досчитывание -------------------------------------------------------

_fill_thread: threading.Thread | None = None
_fill_state: dict[str, Any] = {"running": False, "done": 0, "total": 0, "error": None}


def fill_state() -> dict[str, Any]:
    return dict(_fill_state)


def _try_file_lock(path: Path) -> Any:
    """Неблокирующая межпроцессная блокировка; None — её держит другой процесс."""

    try:
        import fcntl
    except ImportError:  # Windows вне Docker: блокировка только внутри процесса
        return open(path, "a+")  # noqa: SIM115
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def embed_missing(texts: dict[str, str], *, keep_only: bool = False) -> int:
    """Досчитывает векторы для texts (ключ → текст), которых нет в кэше.

    Возвращает число посчитанных. keep_only — заодно удалить из кэша всё, чего
    нет в texts (после удаления документов).
    """

    encoder = get_encoder()
    cache = get_cache()
    if encoder is None or cache is None:
        return 0
    keys = list(texts)
    _, missing = cache.lookup(keys)
    todo = [keys[i] for i in missing]
    done = 0
    for start in range(0, len(todo), 64):
        part = todo[start : start + 64]
        vectors = encoder.encode(
            [texts[k] for k in part], settings.DENSE_DOCUMENT_PREFIX
        )
        cache.add(part, vectors)
        done += len(part)
        _fill_state["done"] = _fill_state.get("done", 0) + len(part)
    if keep_only:
        cache.add([], np.zeros((0, encoder.dim), dtype=np.float32), keep=set(keys))
    return done


def start_background_fill(texts: dict[str, str], *, keep_only: bool = False) -> bool:
    """Запускает досчёт в фоне (один поток на процесс, один процесс на кэш).

    keep_only=True передавайте только с полным списком чанков (без фильтров).
    """

    global _fill_thread
    cache = get_cache()
    if cache is None:
        return False
    if _fill_thread is not None and _fill_thread.is_alive():
        return False

    def run() -> None:
        handle = _try_file_lock(cache.lock_path)
        if handle is None:  # считает другой воркер; его результат придёт через файл
            return
        _fill_state.update(running=True, done=0, total=len(texts), error=None)
        started = time.perf_counter()
        try:
            count = embed_missing(texts, keep_only=keep_only)
            logger.info(
                "dense cache filled: %d new vectors in %.1f s",
                count,
                time.perf_counter() - started,
            )
        except Exception as exc:
            _fill_state["error"] = f"{type(exc).__name__}: {exc}"
            logger.exception("dense cache fill failed")
        finally:
            _fill_state["running"] = False
            handle.close()

    _fill_thread = threading.Thread(target=run, name="dense-fill", daemon=True)
    _fill_thread.start()
    return True


def search(
    question: str, items: Iterable[tuple[str, str]], *, sync_limit: int | None = None
) -> tuple[list[tuple[int, float]], int]:
    """Косинусная близость вопроса к документам.

    items — пары (ключ, текст документа) в порядке строк. Возвращает список
    (позиция, косинус) по убыванию только для документов с вектором и число
    документов без вектора (их досчитывает фон).
    """

    encoder = get_encoder()
    cache = get_cache()
    if encoder is None or cache is None:
        return [], 0
    pairs = list(items)
    if not pairs:
        return [], 0
    keys = [k for k, _ in pairs]
    matrix, missing = cache.lookup(keys)
    limit = settings.DENSE_SYNC_EMBED_LIMIT if sync_limit is None else sync_limit
    if missing and len(missing) <= limit:
        part = [keys[i] for i in missing]
        vectors = encoder.encode(
            [pairs[i][1] for i in missing], settings.DENSE_DOCUMENT_PREFIX
        )
        cache.add(part, vectors)
        matrix[missing] = vectors
        missing = []
    elif missing:
        start_background_fill(dict(pairs))
    query = encoder.encode([question], settings.DENSE_QUERY_PREFIX)[0]
    sims = matrix @ query
    absent = set(missing)
    ranked = [
        (pos, float(sims[pos])) for pos in np.argsort(-sims) if int(pos) not in absent
    ]
    return [(int(p), s) for p, s in ranked], len(missing)


def calibrated_score(cosine: float) -> float:
    """Косинус → 0..1 для маршрутизации (сравнивается с порогом BM25)."""

    floor = float(live_settings.DENSE_SCORE_FLOOR)
    ceil = float(live_settings.DENSE_SCORE_CEIL)
    if ceil <= floor:
        return 1.0 if cosine >= floor else 0.0
    return max(0.0, min(1.0, (cosine - floor) / (ceil - floor)))


def status() -> dict[str, Any]:
    """Состояние добавки для админки и журнала."""

    cache = _cache
    return {
        "model_dir": str(model_dir()),
        "model_available": model_available(),
        "loaded": _encoder is not None,
        "error": _encoder_error,
        "cached_vectors": cache.size() if cache is not None else 0,
        "fill": fill_state(),
    }
