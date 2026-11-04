"""Скачивает веса классификатора Кати и базовую модель rubert-tiny2 в MODEL_DIR.

Запускается один раз при сборке образа, чтобы сервис работал без сети.
Веса сверяются по sha256 из LFS-указателя репозитория Кати: подменённый файл
не будет загружен.
"""

import hashlib
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

WEIGHTS_URL = (
    "https://media.githubusercontent.com/media/KateRastorgueva/Chat-bot/main/"
    + urllib.parse.quote("чат бот/intent_classifier.pt")
)
WEIGHTS_SHA256 = "31762655e347e24c95c363f62e0eceaf4a40a73415867ee0b9ee908e433b694f"
BASE_MODEL = "cointegrated/rubert-tiny2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    model_dir = Path(os.environ.get("MODEL_DIR", "/models/intent"))
    model_dir.mkdir(parents=True, exist_ok=True)
    weights = model_dir / "intent_classifier.pt"

    if not weights.exists() or _sha256(weights) != WEIGHTS_SHA256:
        print(f"Скачиваю веса: {WEIGHTS_URL}")  # noqa: T201
        tmp = weights.with_suffix(".part")
        urllib.request.urlretrieve(WEIGHTS_URL, tmp)
        actual = _sha256(tmp)
        if actual != WEIGHTS_SHA256:
            tmp.unlink(missing_ok=True)
            print(f"sha256 не совпал: {actual}", file=sys.stderr)  # noqa: T201
            return 1
        tmp.replace(weights)

    # Токенизатор и конфиг энкодера: сами веса энкодера лежат в intent_classifier.pt.
    from transformers import AutoConfig, AutoTokenizer

    AutoTokenizer.from_pretrained(BASE_MODEL).save_pretrained(model_dir / "base")
    AutoConfig.from_pretrained(BASE_MODEL).save_pretrained(model_dir / "base")
    print(f"Готово: {model_dir}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
