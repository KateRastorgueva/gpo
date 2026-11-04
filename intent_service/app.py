"""HTTP-сервис классификатора тем вопросов (модель Кати на rubert-tiny2).

Отдельный контейнер, чтобы PyTorch не попадал в образ backend: backend зовёт
`POST /classify` и при любой ошибке просто работает без темы.
"""

import os
import threading
from pathlib import Path
from typing import Any

import torch
from categories import CATEGORIES, CATEGORY_LABELS
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from torch import nn
from transformers import AutoConfig, AutoModel, AutoTokenizer

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models/intent"))
MAX_LEN = 64

torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "2")))


class IntentClassifier(nn.Module):
    """Та же архитектура, что в train_classifier.py Кати: [CLS] -> 256 -> классы."""

    def __init__(self, num_classes: int) -> None:
        super().__init__()
        config = AutoConfig.from_pretrained(MODEL_DIR / "base")
        self.encoder = AutoModel.from_config(config)
        hidden = config.hidden_size
        self.classifier = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(hidden, 256),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(256, num_classes),
        )

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> Any:
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        return self.classifier(out.last_hidden_state[:, 0, :])


class _Model:
    def __init__(self) -> None:
        # weights_only=True: в чекпойнте только тензоры и простые значения,
        # произвольные объекты pickle не распаковываются.
        checkpoint = torch.load(
            MODEL_DIR / "intent_classifier.pt", map_location="cpu", weights_only=True
        )
        num_classes = int(checkpoint["num_classes"])
        if num_classes != len(CATEGORIES):
            raise RuntimeError(
                f"Модель знает {num_classes} тем, а в categories.py {len(CATEGORIES)}"
            )
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR / "base")
        self.net = IntentClassifier(num_classes)
        self.net.load_state_dict(checkpoint["model_state_dict"])
        self.net.eval()

    @torch.no_grad()
    def predict(self, text: str, top_k: int) -> list[tuple[str, float]]:
        enc = self.tokenizer(
            text, truncation=True, max_length=MAX_LEN, return_tensors="pt"
        )
        logits = self.net(enc["input_ids"], enc["attention_mask"])
        probs = torch.softmax(logits, dim=1)[0]
        values, indices = probs.topk(min(top_k, len(CATEGORIES)))
        return [
            (CATEGORIES[int(i)], float(v))
            for v, i in zip(values.tolist(), indices.tolist(), strict=True)
        ]


_model: _Model | None = None
_model_error: str | None = None
_lock = threading.Lock()


def _get_model() -> _Model:
    global _model, _model_error
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    _model = _Model()
                    _model_error = None
                except Exception as exc:  # noqa: BLE001 - отдаём причину в /health
                    _model_error = f"{type(exc).__name__}: {exc}"
                    raise
    return _model


app = FastAPI(title="Intent classifier")


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=3, ge=1, le=24)


class Candidate(BaseModel):
    category: str
    label: str
    confidence: float


class ClassifyResponse(BaseModel):
    category: str
    label: str
    confidence: float
    candidates: list[Candidate]


@app.on_event("startup")
def _warm_up() -> None:
    try:
        _get_model()
    except Exception:  # noqa: BLE001 - сервис поднимется, /health покажет ошибку
        pass


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": _model is not None,
        "error": _model_error,
        "categories": [{"name": c, "label": CATEGORY_LABELS[c]} for c in CATEGORIES],
    }


@app.post("/classify", response_model=ClassifyResponse)
def classify(body: ClassifyRequest) -> ClassifyResponse:
    try:
        model = _get_model()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ranked = model.predict(body.text, body.top_k)
    candidates = [
        Candidate(category=c, label=CATEGORY_LABELS[c], confidence=round(p, 4))
        for c, p in ranked
    ]
    best = candidates[0]
    return ClassifyResponse(
        category=best.category,
        label=best.label,
        confidence=best.confidence,
        candidates=candidates,
    )
