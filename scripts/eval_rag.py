# -*- coding: utf-8 -*-
"""Офлайн-харнесс метрик качества retrieval RAG.

Запуск (не требует Docker/Postgres/Qdrant/LLM):
    python scripts/eval_rag.py

Импортирует реальный backend/app/services/support_service.py и сравнивает
baseline- и улучшенные алгоритмы retrieval на golden-наборе вопросов,
закреплённых за конкретными официальными источниками ТУСУР.

Метрики (на уровне источника):
  * Hit@k   - доля вопросов, где эталонный источник попал в top-k;
  * MRR     - средний обратный ранг первого эталонного источника;
  * nDCG@k  - нормализованный DCG с бинарной релевантностью;
  * Prec@k  - доля релевантных источников среди top-k;
  * sep     - разница среднего top-1 score (вопросы с ответом минус без ответа).
"""

import hashlib
import json
import math
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from app.services import support_service as svc  # noqa: E402

SEED_PATH = os.path.join(ROOT, "scripts", "tusur_sources_seed_v1.json")
K_VALUES = (1, 3, 5)
EMBED_DIM = 384

# --- Golden-набор: (вопрос, эталонный source_url | None = ответа нет) ---
GOLDEN = [
    ("Где смотреть расписание занятий ТУСУР?", "https://timetable.tusur.ru/"),
    ("На каком сайте ТУСУР расписание занятий?", "https://timetable.tusur.ru/"),
    ("Где узнать расписание пар и аудиторий ТУСУР?", "https://timetable.tusur.ru/"),
    ("Подскажите сервис с расписанием групп и преподавателей", "https://timetable.tusur.ru/"),
    ("Какой сайт показывает расписание занятий в ТУСУР?", "https://timetable.tusur.ru/"),
    ("Где контакты приемной комиссии ТУСУР?", "https://abiturient.tusur.ru/ru/kontakty"),
    ("Куда писать по вопросам поступления в ТУСУР?", "https://abiturient.tusur.ru/ru/kontakty"),
    ("Как связаться с приемной комиссией ТУСУР?", "https://abiturient.tusur.ru/ru/kontakty"),
    ("Телефон и почта для абитуриентов ТУСУР", "https://abiturient.tusur.ru/ru/kontakty"),
    ("Где найти контакты для поступающих в ТУСУР?", "https://abiturient.tusur.ru/ru/kontakty"),
    ("Где информация о стипендиях ТУСУР?", "https://tusur.ru/sveden/grants"),
    ("Где посмотреть меры поддержки студентов ТУСУР?", "https://tusur.ru/sveden/grants"),
    ("Какие стипендии и гранты есть в ТУСУР?", "https://tusur.ru/sveden/grants"),
    ("Где официальные сведения о стипендиях ТУСУР?", "https://tusur.ru/sveden/grants"),
    ("Где узнать про материальную поддержку в ТУСУР?", "https://tusur.ru/sveden/grants"),
    ("Где смотреть платные образовательные услуги ТУСУР?", "https://tusur.ru/sveden/paid_edu"),
    ("Где официальная информация по оплате обучения в ТУСУР?", "https://tusur.ru/sveden/paid_edu"),
    ("Сколько стоит обучение и где смотреть договор в ТУСУР?", "https://tusur.ru/sveden/paid_edu"),
    ("Где документы по платному обучению ТУСУР?", "https://tusur.ru/sveden/paid_edu"),
    ("Где информация о стоимости обучения в ТУСУР?", "https://tusur.ru/sveden/paid_edu"),
    ("Где официальные сведения об организации ТУСУР?", "https://tusur.ru/sveden/common"),
    ("Какая страница ТУСУР содержит общие сведения?", "https://tusur.ru/sveden/common"),
    ("Где посмотреть реквизиты и статус ТУСУР?", "https://tusur.ru/sveden/common"),
    ("Где общие сведения об образовательной организации ТУСУР?", "https://tusur.ru/sveden/common"),
    ("Где официальная структура сведений ТУСУР?", "https://tusur.ru/sveden/common"),
    ("Где образовательные программы ТУСУР?", "https://tusur.ru/sveden/education"),
    ("Где информация об образовании в ТУСУР?", "https://tusur.ru/sveden/education"),
    ("Где перечень образовательных программ ТУСУР?", "https://tusur.ru/sveden/education"),
    ("Где смотреть документы об образовании ТУСУР?", "https://tusur.ru/sveden/education"),
    ("На какой странице программы обучения ТУСУР?", "https://tusur.ru/sveden/education"),
    ("Где раздел ТУСУР для студентов?", "https://tusur.ru/ru/studentam"),
    ("Где на сайте ТУСУР полезные ссылки для студента?", "https://tusur.ru/ru/studentam"),
    ("Где на сайте ТУСУР страница для студентов?", "https://tusur.ru/ru/studentam"),
    ("Где вход в студенческие сервисы ТУСУР?", "https://tusur.ru/ru/studentam"),
    ("С какого раздела начать студенту на сайте ТУСУР?", "https://tusur.ru/ru/studentam"),
    ("Какой точный дедлайн оплаты моего договора в этом семестре?", None),
    ("Назовите номер приказа по моему индивидуальному учебному плану", None),
    ("Где в ТУСУР столовые и кафе для студентов?", None),
    ("Как записаться в общежитие ТУСУР?", None),
    ("Где посмотреть расписание экзаменов на завтра?", None),
]


def load_sources():
    with open(SEED_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_chunks(sources):
    chunks = []
    for src in sources:
        for text in svc.chunk_text(src["manual_content"]):
            chunks.append(
                {"source_url": src["source_url"], "source_title": src["title"], "text": text}
            )
    return chunks


# --------------------------------------------------------------------------
# Токенизация: baseline = текущая; improved = текущая + лёгкий русский стемминг
# --------------------------------------------------------------------------
_RU_SUFFIXES = (
    "иями", "ями", "ами", "ией", "иям", "иях", "его", "ому", "ими", "ыми",
    "ого", "ему", "ая", "яя", "ое", "ее", "ые", "ие", "ий", "ый", "ой", "ей",
    "ия", "ие", "ии", "ов", "ев", "ин", "ын", "ах", "ях", "ам", "ям", "ом", "ем",
    "ы", "и", "а", "я", "о", "е", "у", "ю", "ь",
)


def russian_stem(word):
    if len(word) <= 3:
        return word
    for suf in _RU_SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def tokens_baseline(text):
    return list(svc._token_set(text))


def tokens_stem(text):
    return [russian_stem(t) for t in tokens_baseline(text)]


def cosine(a, b):
    if not a or not b:
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return num / (na * nb) if na and nb else 0.0


# --------------------------------------------------------------------------
# Лексический поиск
# --------------------------------------------------------------------------
class TfIdfIndex:
    def __init__(self, docs):
        self.docs = docs
        self.df = Counter()
        self.doc_tokens = []
        for d in docs:
            toks = tokens_stem(d)
            self.doc_tokens.append(toks)
            for t in set(toks):
                self.df[t] += 1
        self.n = len(docs)
        self.doc_vecs = [self.vec(toks) for toks in self.doc_tokens]
        self.vec_by_doc = {d: v for d, v in zip(docs, self.doc_vecs)}

    def _idf(self, t):
        return math.log((self.n + 1.0) / (self.df.get(t, 0) + 1.0)) + 1.0

    def vec(self, toks):
        tf = Counter(toks)
        total = sum(tf.values()) or 1
        return {t: (c / total) * self._idf(t) for t, c in tf.items()}

    def query_vec(self, text):
        return self.vec(tokens_stem(text))

    @staticmethod
    def cosine(a, b):
        if not a or not b:
            return 0.0
        num = sum(v * b.get(k, 0.0) for k, v in a.items())
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return num / (na * nb) if na and nb else 0.0


class Bm25Index:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokens_stem(d) for d in docs]
        self.n = len(docs)
        self.df = Counter()
        self.doc_lens = []
        for toks in self.doc_tokens:
            self.doc_lens.append(len(toks))
            for t in set(toks):
                self.df[t] += 1
        self.avgdl = (sum(self.doc_lens) / self.n) if self.n else 0.0

    def score(self, query, doc_text):
        q = tokens_stem(query)
        tf = Counter(tokens_stem(doc_text))
        dl = len(tf)
        s = 0.0
        for t in q:
            f = tf.get(t, 0)
            if f == 0:
                continue
            idf = math.log((self.n - self.df[t] + 0.5) / (self.df[t] + 0.5) + 1.0)
            s += idf * (f * (self.k1 + 1.0)) / (
                f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
            )
        return s


# --------------------------------------------------------------------------
# Семантический поиск (без внешних моделей)
# --------------------------------------------------------------------------
def char_ngram_embedding(text, dim=EMBED_DIM, n=3):
    """Char-n-gram feature hashing: лексически осмысленный embedding без моделей."""
    grams = Counter()
    for tok in re.findall(r"[a-zа-яё0-9]+", text.lower()):
        tok = "#" + tok + "#"
        for i in range(len(tok) - n + 1):
            grams[tok[i : i + n]] += 1
    vec = [0.0] * dim
    for g, c in grams.items():
        h = int.from_bytes(hashlib.md5(g.encode("utf-8")).digest()[:4], "little")
        vec[h % dim] += float(c)
    norm = math.sqrt(sum(v * v for v in vec))
    if norm:
        vec = [v / norm for v in vec]
    return vec


def sha256_embedding(text, size=384):
    """Прежний резервный embedding на SHA-256 (исторический baseline для сравнения)."""
    text_bytes = text.encode("utf-8", errors="ignore")
    digest = hashlib.sha256(text_bytes).digest()
    output = []
    idx = 0
    while len(output) < size:
        byte_val = digest[idx % len(digest)]
        output.append((byte_val / 127.5) - 1.0)
        idx += 1
    return output


def sem_scorer(embed_fn):
    return lambda q, c: cosine(embed_fn(q), embed_fn(c["text"]))


# --------------------------------------------------------------------------
# Retrieval: полный рейтинг чанков по убыванию score
# --------------------------------------------------------------------------
def rank_by_scorer(query, chunks, scorer):
    scored = [(scorer(query, c), i) for i, c in enumerate(chunks)]
    scored.sort(key=lambda x: -x[0])
    return scored


def minmax(values):
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def rank_hybrid(query, chunks, scorers, weights):
    n = len(chunks)
    raw = [[sc(query, chunks[i]) for i in range(n)] for sc in scorers]
    norm = [minmax(col) for col in raw]
    combined = [sum(w * norm[m][i] for m, w in enumerate(weights)) for i in range(n)]
    ranked = sorted(enumerate(combined), key=lambda x: -x[1])
    return [(s, i) for i, s in ranked]


# --------------------------------------------------------------------------
# Метрики
# --------------------------------------------------------------------------
def unique_source_ranking(ranked, chunks):
    seen, order = [], []
    for _score, idx in ranked:
        url = chunks[idx]["source_url"]
        if url not in seen:
            seen.append(url)
            order.append(url)
    return order


def evaluate(ranked_by_query, chunks, queries):
    hits = {k: 0.0 for k in K_VALUES}
    prec = {k: 0.0 for k in K_VALUES}
    mrr_total = 0.0
    ndcg5_total = 0.0
    for question, expected in queries:
        order = unique_source_ranking(ranked_by_query[question], chunks)
        rel = [1 if u == expected else 0 for u in order]
        for k in K_VALUES:
            if 1 in rel[:k]:
                hits[k] += 1.0
            prec[k] += sum(rel[:k]) / float(k)
        try:
            rank = rel.index(1) + 1
            mrr_total += 1.0 / rank
        except ValueError:
            pass
        dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel[:5]))
        idcg = sum(r / math.log2(i + 2) for i, r in enumerate([1, 0, 0, 0, 0]))
        ndcg5_total += (dcg / idcg) if idcg else 0.0
    n = len(queries)
    return {
        "Hit@1": hits[1] / n,
        "Hit@3": hits[3] / n,
        "Hit@5": hits[5] / n,
        "MRR": mrr_total / n,
        "nDCG@5": ndcg5_total / n,
        "Prec@5": prec[5] / n,
    }


def main():
    sources = load_sources()
    chunks = build_chunks(sources)
    pos = [(q, e) for q, e in GOLDEN if e]
    neg = [(q, e) for q, e in GOLDEN if not e]

    tfidf = TfIdfIndex([c["text"] for c in chunks])
    bm25 = Bm25Index([c["text"] for c in chunks])

    scorers = {
        "lex_f1 (baseline)": lambda q, c: svc._lexical_similarity(
            svc.normalize_text(q), c["text"]
        ),
        "lex_tfidf": lambda q, c: tfidf.cosine(
            tfidf.query_vec(q), tfidf.vec_by_doc[c["text"]]
        ),
        "lex_bm25": lambda q, c: bm25.score(q, c["text"]),
        "sem_sha256 (baseline)": sem_scorer(sha256_embedding),
        "sem_ngram": sem_scorer(char_ngram_embedding),
    }

    ranked = {}
    for name, scorer in scorers.items():
        ranked[name] = {q: rank_by_scorer(q, chunks, scorer) for q, _e in GOLDEN}

    ranked["hybrid_base"] = {
        q: rank_hybrid(
            q,
            chunks,
            [
                sem_scorer(sha256_embedding),
                lambda qq, c: svc._lexical_similarity(svc.normalize_text(qq), c["text"]),
            ],
            [0.7, 0.3],
        )
        for q, _e in GOLDEN
    }
    ranked["hybrid_new"] = {
        q: rank_hybrid(
            q,
            chunks,
            [sem_scorer(char_ngram_embedding), lambda qq, c: bm25.score(qq, c["text"])],
            [0.7, 0.3],
        )
        for q, _e in GOLDEN
    }

    print("Корпус: %d источников -> %d чанков (CHUNK_SIZE=%d)" % (
        len(sources), len(chunks), svc.settings.CHUNK_SIZE))
    print("Golden: %d с ответом, %d без ответа" % (len(pos), len(neg)))
    print()

    header = "%-22s %7s %7s %7s %7s %7s %7s %7s" % (
        "method", "Hit@1", "Hit@3", "Hit@5", "MRR", "nDCG@5", "Prec@5", "sep")
    print(header)
    print("-" * len(header))

    results = {}
    for name, r in ranked.items():
        m = evaluate(r, chunks, pos)
        pos_top1 = [r[q][0][0] for q, _e in pos]
        neg_top1 = [r[q][0][0] for q, _e in neg]
        sep = (sum(pos_top1) / len(pos_top1)) - (sum(neg_top1) / len(neg_top1))
        results[name] = (m, sep)
        print("%-22s %6.1f%% %6.1f%% %6.1f%% %7.3f %7.3f %6.1f%% %7.3f" % (
            name, m["Hit@1"] * 100, m["Hit@3"] * 100, m["Hit@5"] * 100,
            m["MRR"], m["nDCG@5"], m["Prec@5"] * 100, sep))

    print()
    print("baseline  = lex_f1 + sem_sha256 (текущий код)")
    print("improved  = lex_bm25 + sem_ngram (предлагаемый код)")
    return results


if __name__ == "__main__":
    main()
