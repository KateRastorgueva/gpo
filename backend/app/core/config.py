import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    GOOGLE_API_KEY: str | None = None
    GOOGLE_MODEL: str = "gemini-flash-latest"
    GOOGLE_EMBEDDING_MODEL: str = "gemini-embedding-001"
    GOOGLE_API_URL: str = "https://generativelanguage.googleapis.com/v1beta"

    # Ключ AI Studio. Если не задан, используется GOOGLE_API_KEY.
    GEMINI_API_KEY: str | None = None

    # Какой движок отвечает после промаха FAQ:
    # legacy (собственный поиск + LLM) | search_only (собственный поиск без LLM:
    # пользователю показываются найденные фрагменты) | gemini_file_search | anythingllm.
    RAG_PROVIDER: str = "legacy"
    GEMINI_FILE_SEARCH_STORE: str | None = None
    # Модели по порядку предпочтения, через запятую.
    GEMINI_FILE_SEARCH_MODEL: str = (
        "gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest"
    )
    GEMINI_FILE_SEARCH_TOP_K: int = 8
    ANYTHINGLLM_BASE_URL: str = "http://anythingllm:3001"
    ANYTHINGLLM_API_KEY: str | None = None
    ANYTHINGLLM_WORKSPACE: str = "tusur"
    RAG_PROVIDER_TIMEOUT_SECONDS: int = 90

    # Журнал событий хоста (JSON Lines): запросы, ответы RAG, загрузки, ошибки.
    EVENT_LOG_ENABLED: bool = True
    EVENT_LOG_DIR: str = "/app/logs"
    EVENT_LOG_RETENTION_DAYS: int = 30
    # Писать ли текст вопроса (первые 500 символов). Ответ целиком не пишется.
    EVENT_LOG_QUESTIONS: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gemini_api_key(self) -> str | None:
        return self.GEMINI_API_KEY or self.GOOGLE_API_KEY

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    OLLAMA_TIMEOUT_SECONDS: int = 30

    # LM Studio (OpenAI-совместимый сервер) для генерации во встроенном поиске.
    # Пусто — LM Studio не используется. Из контейнера backend на хосте это
    # http://host.docker.internal:1234/v1 (см. compose.override.yml).
    LMSTUDIO_BASE_URL: str = ""
    LMSTUDIO_MODEL: str = "qwen2.5-14b-instruct"
    LMSTUDIO_TIMEOUT_SECONDS: int = 120

    # Векторный слой встроенного поиска (Qdrant + embeddings). Выключен — поиск
    # идёт только BM25 по чанкам в Postgres: не нужны ни контейнер Qdrant, ни
    # модель embeddings. При встроенном hashed-эмбеддере Qdrant качества почти не
    # добавляет, поэтому по умолчанию он выключен (docs/laptop-search-only.md).
    VECTOR_SEARCH_ENABLED: bool = False

    # Векторная добавка к BM25 без Qdrant и без torch (docs/laptop-dense-search.md):
    # маленькая русская модель (rubert-mini-frida, ~125 МБ) считается в numpy,
    # векторы чанков кэшируются на диске, списки BM25 и векторов склеиваются RRF.
    # Включается, только если задан каталог модели и включён флаг.
    DENSE_SEARCH_ENABLED: bool = False
    LOCAL_EMBEDDING_MODEL_DIR: str = "/models/rubert-mini-frida"
    DENSE_CACHE_DIR: str = "/app/dense-cache"
    DENSE_MAX_TOKENS: int = 256
    DENSE_QUERY_PREFIX: str = "search_query: "
    DENSE_DOCUMENT_PREFIX: str = "search_document: "
    # Косинус ниже FLOOR даёт оценку 0, выше CEIL — 1 (линейно между ними).
    # Оценка сравнивается с RAG_TOP_SCORE_THRESHOLD_HASHED так же, как покрытие BM25.
    DENSE_SCORE_FLOOR: float = 0.45
    DENSE_SCORE_CEIL: float = 0.75
    # Сколько недостающих чанков досчитать прямо в запросе; больше — в фоне.
    DENSE_SYNC_EMBED_LIMIT: int = 64

    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION_NAME: str = "knowledge_chunks"
    QDRANT_TIMEOUT_SECONDS: int = 30

    EMBEDDING_MODEL_NAME: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    EMBEDDING_DIM: int = 384
    # auto | sentence-transformers | google | hashed. "auto" picks one backend
    # per process (sentence-transformers -> google -> hashed) and never mixes them.
    EMBEDDING_BACKEND: str = "auto"

    FAQ_SIMILARITY_THRESHOLD: float = 0.90
    RAG_TOP_SCORE_THRESHOLD: float = 0.72
    RAG_RELEVANT_CHUNK_THRESHOLD: float = 0.60
    RAG_MIN_RELEVANT_CHUNKS: int = 2
    # Score scales differ per embedding backend: the char-n-gram fallback never
    # reaches the thresholds tuned for sentence-transformers. Calibrated with
    # scripts/calibrate_routing.py, see docs/reviews/2026-10-07-doc-pipeline-review.md.
    # Покрытие запроса лучшим чанком (BM25 без векторов или hashed-эмбеддинги).
    # 0.5 вместо прежних 0.25: на 49 документах ТУСУР посторонние вопросы
    # («рецепт борща», «чемпионат мира») набирали 0.2–0.46 и получали «ответ»,
    # а верные находки — от 0.51 (docs/laptop-search-only.md, раздел «Замеры»).
    RAG_TOP_SCORE_THRESHOLD_HASHED: float = 0.5
    RAG_RELEVANT_CHUNK_THRESHOLD_HASHED: float = 0.25
    RAG_MIN_RELEVANT_CHUNKS_HASHED: int = 1
    # Фильтр офтопа (services/offtopic.py): выключен по умолчанию.
    OFFTOPIC_FILTER_ENABLED: bool = False
    OFFTOPIC_MIN_MEAN_SIMILARITY: float = 0.30
    OFFTOPIC_TOP_N: int = 5
    CRITICAL_CONFIDENCE_THRESHOLD: float = 0.80
    LOW_CONFIDENCE_MIN: float = 0.65
    LOW_CONFIDENCE_MAX: float = 0.79
    RETRIEVAL_TOP_K: int = 5
    HYBRID_CANDIDATES_LIMIT: int = 20
    HYBRID_SEMANTIC_WEIGHT: float = 0.7
    HYBRID_LEXICAL_WEIGHT: float = 0.3
    RERANK_WEIGHT: float = 0.25
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150

    MAX_UPLOAD_SIZE_MB: int = 20
    URL_FETCH_TIMEOUT_SECONDS: int = 20
    URL_FETCH_USER_AGENT: str = "KSUP-2501-ingest/1.0"

    # Ретенция архива знаний: сколько последних версий хранить на источник (риск R4 плана).
    KNOWLEDGE_ARCHIVE_MAX_VERSIONS: int = 20

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
