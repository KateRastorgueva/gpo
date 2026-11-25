"""Обучение альтернативного классификатора тем по базе Help Desk ТУСУР.

Датасет — CSV из проекта ``tusur_bot`` (``checkpoints/dataset.csv``) с колонками
``question``, ``category``, ``split``: 99 000 вопросов, 22 категории про
IT-сервисы ТУСУР (Личный кабинет, Журнал посещаемости, Облачное хранилище…).

Модель намеренно лёгкая: TF-IDF (1–2 граммы) + логистическая регрессия.
Артефакт сохраняется **без sklearn** (`.npz`: словарь, idf, веса, классы), чтобы
инференс в контейнере не зависел от версии scikit-learn — в ``helpdesk.py``
считается тем же TF-IDF на numpy.

Запуск (нужны pandas, scikit-learn, numpy):

    python scripts/train_intent_helpdesk.py \
        --dataset "C:/path/to/tusur_bot/checkpoints/dataset.csv" \
        --out intent_service/models/helpdesk_tfidf.npz

Артефакт коммитится в репозиторий; сам датасет — нет.
"""

from __future__ import annotations

import argparse
import pathlib
import time

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

DEFAULT_OUT = pathlib.Path("intent_service/models/helpdesk_tfidf.npz")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=pathlib.Path)
    parser.add_argument("--out", default=DEFAULT_OUT, type=pathlib.Path)
    parser.add_argument("--max-features", default=120_000, type=int)
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    frame["category"] = frame["category"].astype(str)
    questions = frame["question"].astype(str).str.lower()
    labels = frame["category"].to_numpy()

    train_mask = (frame["split"] == "train").to_numpy()
    test_mask = (frame["split"] == "test").to_numpy()

    started = time.monotonic()
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
        max_features=args.max_features,
    )
    x_train = vectorizer.fit_transform(questions[train_mask])
    x_test = vectorizer.transform(questions[test_mask])
    classifier = LogisticRegression(max_iter=300)
    classifier.fit(x_train, labels[train_mask])
    elapsed = time.monotonic() - started

    probabilities = classifier.predict_proba(x_test)
    classes = classifier.classes_
    order = np.argsort(-probabilities, axis=1)[:, :5]
    actual = labels[test_mask]
    top1 = float(np.mean(classes[order[:, 0]] == actual))
    top5 = float(np.mean([actual[i] in classes[order[i]] for i in range(len(order))]))

    # Портативный артефакт: только числа и строки, без pickled-объектов sklearn.
    vocabulary = vectorizer.vocabulary_
    # unicode-массив, а не object: артефакт грузится с allow_pickle=False.
    terms = np.array(list(vocabulary.keys()), dtype=str)
    indices = np.array([vocabulary[term] for term in terms], dtype=np.int64)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        terms=terms,
        term_indices=indices,
        idf=vectorizer.idf_.astype(np.float32),
        coef=classifier.coef_.astype(np.float32),
        intercept=classifier.intercept_.astype(np.float32),
        classes=np.array([str(c) for c in classes], dtype=str),
        ngram_min=np.array([1]),
        ngram_max=np.array([2]),
        sublinear=np.array([1]),
    )
    size_mb = args.out.stat().st_size / 1e6

    print(f"обучено на {int(train_mask.sum())} вопросах за {elapsed:.1f} с")
    print(f"тест {int(test_mask.sum())}: top-1 {top1:.4f}, top-5 {top5:.4f}")
    print(f"классов: {len(classes)} | терминов: {len(terms)} | артефакт: {args.out} ({size_mb:.1f} МБ)")


if __name__ == "__main__":
    main()
