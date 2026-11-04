"""Настройки, которые админ меняет в интерфейсе («Управление → Настройки»).

Зачем: ключи API, адреса движков, модели и пороги маршрутизации раньше жили
только в ``.env``, и любое изменение требовало правки файла и перезапуска
контейнера. Теперь:

* ``.env`` задаёт только запуск (база, ``SECRET_KEY``, первый админ, домен)
  и значения по умолчанию для настроек ниже;
* админ переопределяет любую настройку из ``SPECS`` в интерфейсе, значение
  ложится в таблицу ``app_setting`` и действует без перезапуска;
* секреты (API-ключи) хранятся зашифрованными ключом, выведенным из
  ``SECRET_KEY``: дамп базы, переданный другому человеку, ключей не раскрывает;
* всё, кроме секретов, выгружается и загружается одним YAML-файлом.

Код сервисов читает настройки через ``live_settings`` вместо ``settings``:
у переопределённых в админке ключей берётся значение из БД, у остальных —
из ``.env``. Значения кэшируются на несколько секунд, чтобы не ходить в БД на
каждое обращение; запись из админки сбрасывает кэш своего процесса сразу,
остальные воркеры подхватят изменение по истечении TTL.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import yaml
from cryptography.fernet import Fernet, InvalidToken
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import AppSetting, get_datetime_utc

logger = logging.getLogger(__name__)

Kind = Literal["str", "url", "int", "float", "bool", "secret", "choice"]

DB_PREFIX = "cfg:"
ENCRYPTED_PREFIX = "enc:"
CACHE_TTL_SECONDS = 5.0
YAML_HEADER = (
    "# Конфигурация КСУП-2501: «Управление → Настройки → Скачать YAML».\n"
    "# Список блоков: id — группа настроек, config — её значения.\n"
    "# null — оставить как есть. API-ключи в выгрузку не попадают;\n"
    "# чтобы задать ключ при загрузке, впишите его строкой вместо null.\n"
)


@dataclass(frozen=True)
class SettingSpec:
    key: str  # имя атрибута в app.core.config.Settings
    group: str
    yaml_key: str
    label: str
    kind: Kind = "str"
    help: str = ""
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    # Своя строка в app_setting (переключатель движка из PR «Движки RAG»).
    db_key: str | None = None
    # Значение по умолчанию для настроек, которых нет в .env (Settings).
    default: Any = None

    @property
    def storage_key(self) -> str:
        return self.db_key or f"{DB_PREFIX}{self.key}"


@dataclass(frozen=True)
class GroupSpec:
    id: str
    name: str
    label: str
    help: str = ""


GROUPS: tuple[GroupSpec, ...] = (
    GroupSpec(
        "rag",
        "@ksup/rag-engine",
        "Движок ответов",
        "Кто отвечает после промаха FAQ. Быстрый переключатель — во вкладке «Движки RAG».",
    ),
    GroupSpec(
        "gemini",
        "@ksup/rag-gemini",
        "Облако: Google Gemini",
        "Ключ AI Studio используется и File Search, и встроенным поиском (embeddings, ответы).",
    ),
    GroupSpec("anythingllm", "@ksup/rag-anythingllm", "Локально: AnythingLLM"),
    GroupSpec(
        "llm",
        "@ksup/llm-ollama",
        "LLM встроенного поиска (Ollama)",
        "Пишет текст ответа, когда работает встроенный поиск и нет ключа Google.",
    ),
    GroupSpec(
        "routing",
        "@ksup/routing",
        "Маршрутизация FAQ → RAG → оператор",
        "Пороги уверенности встроенного поиска. Меняйте по одному и проверяйте на типовых вопросах.",
    ),
    GroupSpec(
        "intent",
        "@ksup/intent-classifier",
        "Классификатор тем",
        "Модель Кати называет тему вопроса (стипендия, общежитие, ГПО…) для журнала, "
        "очереди оператора и метрик. Нужен контейнер: docker compose --profile intent up -d intent.",
    ),
    GroupSpec(
        "offtopic",
        "@ksup/offtopic",
        "Фильтр офтопа",
        "Вежливый отказ на вопросы не по теме вместо передачи оператору. "
        "Кнопка «Передать оператору» остаётся у пользователя.",
    ),
)

_PROVIDERS = ("legacy", "search_only", "gemini_file_search", "anythingllm")

SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        "RAG_PROVIDER",
        "rag",
        "provider",
        "Активный движок",
        "choice",
        "legacy — встроенный поиск + LLM; search_only — встроенный поиск без LLM "
        "(найденные фрагменты с источниками); gemini_file_search — облако; "
        "anythingllm — локально.",
        choices=_PROVIDERS,
        db_key="rag_provider",
    ),
    SettingSpec(
        "VECTOR_SEARCH_ENABLED",
        "rag",
        "vectorSearch",
        "Векторный поиск (Qdrant)",
        "bool",
        "Только для встроенного поиска. Выключен — BM25 по Postgres, без Qdrant и "
        "модели embeddings. Включайте, если запущен контейнер qdrant "
        "(docker compose --profile qdrant), затем «Переиндексировать».",
    ),
    SettingSpec(
        "DENSE_SEARCH_ENABLED",
        "rag",
        "denseSearch",
        "Векторная добавка без Qdrant (лёгкая модель)",
        "bool",
        "Для встроенного поиска и «Только поиск»: к BM25 добавляется поиск по смыслу "
        "маленькой русской моделью (rubert-mini-frida, ~125 МБ, без torch и Qdrant). "
        "Находит синонимы («стоит» → «стоимость»). Нужны файлы модели в каталоге ниже. "
        "Векторы документов считаются в фоне при первом вопросе (несколько минут).",
    ),
    SettingSpec(
        "LOCAL_EMBEDDING_MODEL_DIR",
        "rag",
        "denseModelDir",
        "Каталог модели векторной добавки",
        help="Внутри контейнера backend; в compose папка _local/models примонтирована в /models. Смена каталога — после перезапуска backend.",
    ),
    SettingSpec(
        "RAG_PROVIDER_TIMEOUT_SECONDS",
        "rag",
        "timeoutSeconds",
        "Таймаут запроса к движку, с",
        "int",
        minimum=5,
        maximum=600,
    ),
    SettingSpec(
        "GOOGLE_API_KEY",
        "gemini",
        "apiKey",
        "API-ключ Google AI Studio",
        "secret",
        "aistudio.google.com → Get API key.",
    ),
    SettingSpec(
        "GEMINI_FILE_SEARCH_STORE",
        "gemini",
        "fileSearchStore",
        "Хранилище File Search",
        help="Вида fileSearchStores/имя-xxxx.",
    ),
    SettingSpec(
        "GEMINI_FILE_SEARCH_MODEL",
        "gemini",
        "models",
        "Модели по порядку предпочтения",
        help="Через запятую; следующая берётся, если предыдущая недоступна или исчерпана квота.",
    ),
    SettingSpec(
        "GEMINI_FILE_SEARCH_TOP_K",
        "gemini",
        "topK",
        "Сколько фрагментов искать (top-K)",
        "int",
        minimum=1,
        maximum=50,
    ),
    SettingSpec(
        "GOOGLE_MODEL",
        "gemini",
        "answerModel",
        "Модель ответов встроенного поиска",
    ),
    SettingSpec(
        "GOOGLE_API_URL",
        "gemini",
        "apiUrl",
        "Адрес API",
        "url",
    ),
    SettingSpec(
        "ANYTHINGLLM_BASE_URL",
        "anythingllm",
        "baseUrl",
        "Адрес AnythingLLM",
        "url",
        "В Docker — http://anythingllm:3001, на хосте — http://host.docker.internal:3001.",
    ),
    SettingSpec(
        "ANYTHINGLLM_API_KEY",
        "anythingllm",
        "apiKey",
        "API-ключ AnythingLLM",
        "secret",
        "AnythingLLM → Settings → Developer API → Generate New API Key.",
    ),
    SettingSpec(
        "ANYTHINGLLM_WORKSPACE",
        "anythingllm",
        "workspace",
        "Workspace (slug)",
    ),
    SettingSpec("OLLAMA_BASE_URL", "llm", "baseUrl", "Адрес Ollama", "url"),
    SettingSpec("OLLAMA_MODEL", "llm", "model", "Модель"),
    SettingSpec(
        "OLLAMA_TIMEOUT_SECONDS",
        "llm",
        "timeoutSeconds",
        "Таймаут, с",
        "int",
        minimum=1,
        maximum=600,
    ),
    SettingSpec(
        "FAQ_SIMILARITY_THRESHOLD",
        "routing",
        "faqSimilarity",
        "Порог совпадения с FAQ",
        "float",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "RAG_TOP_SCORE_THRESHOLD",
        "routing",
        "ragTopScore",
        "Порог лучшего фрагмента",
        "float",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "RAG_TOP_SCORE_THRESHOLD_HASHED",
        "routing",
        "ragTopScoreLexical",
        "Порог лучшего фрагмента без векторов (BM25)",
        "float",
        "Доля слов вопроса, найденных в лучшем фрагменте. Действует, когда "
        "векторный поиск выключен. Ниже порога — вопрос уходит оператору.",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "DENSE_SCORE_FLOOR",
        "routing",
        "denseScoreFloor",
        "Векторная добавка: косинус, дающий оценку 0",
        "float",
        "Косинус между FLOOR и CEIL линейно переводится в оценку 0..1 и сравнивается "
        "с порогом лучшего фрагмента BM25.",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "DENSE_SCORE_CEIL",
        "routing",
        "denseScoreCeil",
        "Векторная добавка: косинус, дающий оценку 1",
        "float",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "RAG_RELEVANT_CHUNK_THRESHOLD",
        "routing",
        "ragRelevantChunk",
        "Порог релевантного фрагмента",
        "float",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "RAG_MIN_RELEVANT_CHUNKS",
        "routing",
        "ragMinRelevantChunks",
        "Минимум релевантных фрагментов",
        "int",
        minimum=1,
        maximum=20,
    ),
    SettingSpec(
        "CRITICAL_CONFIDENCE_THRESHOLD",
        "routing",
        "criticalConfidence",
        "Уверенность для критичных тем",
        "float",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "LOW_CONFIDENCE_MIN",
        "routing",
        "lowConfidenceMin",
        "Низкая уверенность: от",
        "float",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "LOW_CONFIDENCE_MAX",
        "routing",
        "lowConfidenceMax",
        "Низкая уверенность: до",
        "float",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "OFFTOPIC_FILTER_ENABLED",
        "offtopic",
        "enabled",
        "Включить фильтр офтопа",
        "bool",
        "Выключен по умолчанию. Правила «мусора» (пустой ввод, «ааааа», русский "
        "текст в латинской раскладке) работают для любого движка; проверка по "
        "сходству — только со встроенным поиском и включённой векторной добавкой.",
    ),
    SettingSpec(
        "OFFTOPIC_MIN_MEAN_SIMILARITY",
        "offtopic",
        "minMeanSimilarity",
        "Порог среднего сходства top-N",
        "float",
        "Среднее косинусов лучших фрагментов к вопросу (rubert-mini-frida). "
        "Ниже порога вопрос считается офтопом и получает вежливый отказ без "
        "записи в очередь. Подбирайте по логам: выше порог — больше отказов, "
        "в том числе по теме.",
        minimum=0,
        maximum=1,
    ),
    SettingSpec(
        "OFFTOPIC_TOP_N",
        "offtopic",
        "topN",
        "Сколько лучших фрагментов усреднять",
        "int",
        minimum=1,
        maximum=20,
    ),
    SettingSpec(
        "RETRIEVAL_TOP_K",
        "routing",
        "retrievalTopK",
        "Фрагментов в ответ (top-K)",
        "int",
        minimum=1,
        maximum=50,
    ),
    SettingSpec(
        "INTENT_CLASSIFIER_ENABLED",
        "intent",
        "enabled",
        "Классификатор включён",
        "bool",
        "Выключен — обращения сохраняются без темы, как раньше.",
        default=False,
    ),
    SettingSpec(
        "INTENT_CLASSIFIER_THRESHOLD",
        "intent",
        "threshold",
        "Порог уверенности",
        "float",
        "Ниже порога тема не записывается. Проверить вопрос — вкладка «Классификатор тем».",
        minimum=0,
        maximum=1,
        default=0.5,
    ),
    SettingSpec(
        "INTENT_CLASSIFIER_URL",
        "intent",
        "serviceUrl",
        "Адрес сервиса",
        "url",
        "В Docker — http://intent:8000.",
        default="http://intent:8000",
    ),
)

SPECS_BY_KEY: dict[str, SettingSpec] = {s.key: s for s in SPECS}
_SPECS_BY_STORAGE: dict[str, SettingSpec] = {s.storage_key: s for s in SPECS}


class SettingsValidationError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


# --- шифрование секретов ---------------------------------------------------


def _fernet() -> Fernet:
    digest = hashlib.sha256(
        b"ksup-app-setting:" + settings.SECRET_KEY.encode()
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return ENCRYPTED_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(stored: str) -> str:
    """Расшифровать; ``InvalidToken`` — значит сменился ``SECRET_KEY``."""
    if not stored.startswith(ENCRYPTED_PREFIX):
        return stored
    return _fernet().decrypt(stored[len(ENCRYPTED_PREFIX) :].encode()).decode()


def secret_hint(value: str | None) -> str | None:
    if not value:
        return None
    return "…" + value[-4:] if len(value) > 8 else "…"


# --- разбор и проверка значений -------------------------------------------


def parse_value(spec: SettingSpec, raw: Any) -> Any:
    """Привести значение к типу настройки или выбросить ``ValueError``."""
    if spec.kind == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("true", "1", "yes", "on", "да"):
            return True
        if text in ("false", "0", "no", "off", "нет"):
            return False
        raise ValueError("ожидается true или false")
    if spec.kind in ("int", "float"):
        if isinstance(raw, bool):
            raise ValueError("ожидается число")
        try:
            number: int | float = (
                int(str(raw).strip())
                if spec.kind == "int"
                else float(str(raw).strip().replace(",", "."))
            )
        except ValueError as exc:
            raise ValueError(
                "ожидается целое число" if spec.kind == "int" else "ожидается число"
            ) from exc
        if spec.minimum is not None and number < spec.minimum:
            raise ValueError(f"не меньше {spec.minimum:g}")
        if spec.maximum is not None and number > spec.maximum:
            raise ValueError(f"не больше {spec.maximum:g}")
        return number
    text = str(raw).strip()
    if not text:
        raise ValueError("пустое значение")
    if len(text) > 500:
        raise ValueError("слишком длинное значение")
    if spec.kind == "choice" and text not in spec.choices:
        raise ValueError("допустимо: " + ", ".join(spec.choices))
    if spec.kind == "url" and not text.startswith(("http://", "https://")):
        raise ValueError("адрес должен начинаться с http:// или https://")
    return text


def _decode_row(spec: SettingSpec, stored: str) -> Any:
    if spec.kind == "secret":
        return decrypt_secret(stored)
    return parse_value(spec, stored)


# --- кэш переопределений ---------------------------------------------------

_lock = threading.Lock()
_cache: tuple[float, dict[str, Any], set[str]] | None = None


def invalidate_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def _read_overrides(session: Session) -> tuple[dict[str, Any], set[str]]:
    rows = session.exec(
        select(AppSetting).where(col(AppSetting.key).in_(list(_SPECS_BY_STORAGE)))
    ).all()
    values: dict[str, Any] = {}
    broken: set[str] = set()
    for row in rows:
        spec = _SPECS_BY_STORAGE[row.key]
        try:
            values[spec.key] = _decode_row(spec, row.value)
        except (InvalidToken, ValueError):
            broken.add(spec.key)
    return values, broken


def _overrides() -> tuple[dict[str, Any], set[str]]:
    global _cache
    now = time.monotonic()
    cached = _cache
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1], cached[2]
    from app.core.db import engine  # локально: app.core.db тянет crud и модели

    try:
        with Session(engine) as session:
            values, broken = _read_overrides(session)
    except Exception:  # БД недоступна — работаем на значениях из .env
        logger.warning("app_setting недоступна, беру настройки из .env", exc_info=True)
        return {}, set()
    with _lock:
        _cache = (now, values, broken)
    return values, broken


class LiveSettings:
    """``settings`` с учётом переопределений из админки.

    Атрибуты, которых нет в ``SPECS``, читаются из ``settings`` как есть.
    """

    def __getattr__(self, name: str) -> Any:
        spec = SPECS_BY_KEY.get(name)
        if spec is None:
            return getattr(settings, name)
        values, _ = _overrides()
        if name in values:
            return values[name]
        return _env_default(spec)

    @property
    def gemini_api_key(self) -> str | None:
        values, _ = _overrides()
        if values.get("GOOGLE_API_KEY"):
            return str(values["GOOGLE_API_KEY"])
        return settings.gemini_api_key


live_settings = LiveSettings()


# --- чтение и запись для админки ------------------------------------------


def _env_default(spec: SettingSpec) -> Any:
    if spec.key == "GOOGLE_API_KEY":
        return settings.gemini_api_key
    return getattr(settings, spec.key, spec.default)


def describe(session: Session) -> list[dict[str, Any]]:
    """Все группы и поля для формы; секреты — только подсказкой «…abcd»."""
    values, broken = _read_overrides(session)
    groups: list[dict[str, Any]] = []
    for group in GROUPS:
        fields: list[dict[str, Any]] = []
        for spec in SPECS:
            if spec.group != group.id:
                continue
            overridden = spec.key in values or spec.key in broken
            default = _env_default(spec)
            field: dict[str, Any] = {
                "key": spec.key,
                "yaml_key": spec.yaml_key,
                "label": spec.label,
                "kind": spec.kind,
                "help": spec.help,
                "choices": list(spec.choices),
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "overridden": overridden,
                "error": (
                    "Не удалось расшифровать: сменился SECRET_KEY. Введите заново."
                    if spec.key in broken
                    else None
                ),
            }
            if spec.kind == "secret":
                current = values.get(spec.key) or default
                field["value"] = None
                field["default"] = None
                field["is_set"] = bool(current)
                field["hint"] = secret_hint(current)
                field["source"] = (
                    "admin" if spec.key in values else ("env" if default else None)
                )
            else:
                field["value"] = values.get(spec.key, default)
                field["default"] = default
            fields.append(field)
        groups.append(
            {
                "id": group.id,
                "name": group.name,
                "label": group.label,
                "help": group.help,
                "fields": fields,
            }
        )
    return groups


def apply_changes(
    session: Session,
    values: dict[str, Any] | None = None,
    reset: list[str] | None = None,
) -> list[str]:
    """Записать значения и сбросы атомарно: при любой ошибке ничего не меняется.

    ``None`` в ``values`` — не трогать (так приходят нетронутые секреты).
    Возвращает список изменённых ключей.
    """
    values = values or {}
    reset = reset or []
    errors: dict[str, str] = {}
    parsed: dict[str, Any] = {}
    for key, raw in values.items():
        spec = SPECS_BY_KEY.get(key)
        if spec is None:
            errors[key] = "неизвестная настройка"
            continue
        if raw is None:
            continue
        try:
            parsed[key] = parse_value(spec, raw)
        except ValueError as exc:
            errors[key] = str(exc)
    for key in reset:
        if key not in SPECS_BY_KEY:
            errors[key] = "неизвестная настройка"
    if errors:
        raise SettingsValidationError(errors)

    lo = parsed.get("LOW_CONFIDENCE_MIN", live_settings.LOW_CONFIDENCE_MIN)
    hi = parsed.get("LOW_CONFIDENCE_MAX", live_settings.LOW_CONFIDENCE_MAX)
    if ("LOW_CONFIDENCE_MIN" in parsed or "LOW_CONFIDENCE_MAX" in parsed) and lo > hi:
        raise SettingsValidationError(
            {"LOW_CONFIDENCE_MIN": "«от» должно быть не больше «до»"}
        )

    changed: list[str] = []
    now = get_datetime_utc()
    for key in reset:
        row = session.get(AppSetting, SPECS_BY_KEY[key].storage_key)
        if row is not None:
            session.delete(row)
            changed.append(key)
    for key, value in parsed.items():
        spec = SPECS_BY_KEY[key]
        if spec.kind == "secret":
            stored = encrypt_secret(value)
        elif spec.kind == "bool":
            stored = "true" if value else "false"
        else:
            stored = str(value)
        row = session.get(AppSetting, spec.storage_key)
        if row is None:
            row = AppSetting(key=spec.storage_key, value=stored)
        row.value = stored
        row.updated_at = now
        session.add(row)
        changed.append(key)
    session.commit()
    invalidate_cache()
    return changed


# --- YAML ------------------------------------------------------------------


def export_yaml(session: Session) -> str:
    values, _ = _read_overrides(session)
    blocks: list[dict[str, Any]] = []
    for group in GROUPS:
        config: dict[str, Any] = {}
        for spec in SPECS:
            if spec.group != group.id:
                continue
            config[spec.yaml_key] = (
                None
                if spec.kind == "secret"
                else values.get(spec.key, _env_default(spec))
            )
        blocks.append({"id": group.id, "name": group.name, "config": config})
    body = yaml.safe_dump(blocks, allow_unicode=True, sort_keys=False)
    return YAML_HEADER + body


def import_yaml(session: Session, text: str) -> dict[str, list[str]]:
    """Загрузить YAML из ``export_yaml``. Неизвестные блоки и ключи пропускаются."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SettingsValidationError({"yaml": f"не разобрать YAML: {exc}"}) from exc
    if data is None:
        data = []
    if not isinstance(data, list):
        raise SettingsValidationError(
            {"yaml": "ожидается список блоков вида «- id: … config: …»"}
        )
    by_yaml = {(s.group, s.yaml_key): s for s in SPECS}
    known_groups = {g.id for g in GROUPS}
    values: dict[str, Any] = {}
    ignored: list[str] = []
    for index, block in enumerate(data):
        if not isinstance(block, dict) or "id" not in block:
            raise SettingsValidationError({"yaml": f"блок №{index + 1} без id"})
        group_id = str(block["id"])
        if group_id not in known_groups:
            ignored.append(group_id)
            continue
        config = block.get("config") or {}
        if not isinstance(config, dict):
            raise SettingsValidationError({group_id: "config должен быть словарём"})
        for yaml_key, raw in config.items():
            spec = by_yaml.get((group_id, str(yaml_key)))
            if spec is None:
                ignored.append(f"{group_id}.{yaml_key}")
                continue
            if raw is None or (spec.kind == "secret" and str(raw).strip() == ""):
                continue
            values[spec.key] = raw
    # Значение, совпадающее с .env, не превращаем в переопределение: иначе
    # после загрузки файла правка .env перестала бы на что-либо влиять.
    current, _ = _read_overrides(session)
    for key in list(values):
        spec = SPECS_BY_KEY[key]
        if key in current or spec.kind == "secret":
            continue
        try:
            same = parse_value(spec, values[key]) == _env_default(spec)
        except ValueError:
            continue  # ошибку покажет apply_changes
        if same:
            del values[key]
    changed = apply_changes(session, values=values)
    return {"applied": changed, "ignored": ignored}
