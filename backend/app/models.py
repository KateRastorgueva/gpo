import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import EmailStr
from sqlalchemy import JSON, CheckConstraint, DateTime, Index, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Wildcard разрешений: роль с ним получает доступ ко всему. Константа живёт здесь, чтобы
# `app/core/permissions.py` мог её импортировать (models не зависит от core — нет цикла).
PERMISSION_WILDCARD = "*"


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    # Если не указана — назначается роль по умолчанию (DEFAULT_ROLE_NAME)
    role_id: uuid.UUID | None = None


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role_id: uuid.UUID | None = None


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Role (RBAC). Разрешения хранятся списком строк; "*" означает доступ ко всему.
class Role(SQLModel, table=True):
    __tablename__ = "role"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=50)
    permissions: list[str] = Field(default_factory=list, sa_type=JSON)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    users: list["User"] = Relationship(back_populates="role")


# Database model, database table inferred from class name
class User(UserBase, table=True):
    __tablename__ = "app_user"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    # role_id намеренно НЕ NOT NULL: пользователей создают и в обход crud (тесты, /private),
    # а отсутствие роли трактуется как «нет прав» в has_permission. Ужесточение до NOT NULL —
    # отдельным шагом, после аудита всех путей создания пользователя.
    role_id: uuid.UUID | None = Field(default=None, foreign_key="role.id", index=True)
    phone: str | None = Field(default=None, max_length=32)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    role: Role | None = Relationship(back_populates="users")
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)

    @property
    def is_superuser(self) -> bool:
        """Производный признак администратора — для совместимости API с фронтендом.

        Отдельной колонки в БД больше нет (миграция M10): права определяет роль.
        """
        role = self.role
        return role is not None and PERMISSION_WILDCARD in (role.permissions or [])

    @property
    def role_name(self) -> str | None:
        """Имя роли для отображения в админке (производное поле, не колонка)."""
        role = self.role
        return role.name if role is not None else None

    @property
    def permissions(self) -> list[str]:
        """Права роли: по ним UI решает, какие разделы и действия показывать."""
        role = self.role
        return list(role.permissions or []) if role is not None else []


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    # Производное поле: True, если у роли есть wildcard-разрешение
    is_superuser: bool = False
    role_id: uuid.UUID | None = None
    role_name: str | None = None
    # Список прав роли (может содержать "*"); пустой список — нет доступа к админке
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class RolePublic(SQLModel):
    id: uuid.UUID
    name: str
    permissions: list[str] = Field(default_factory=list)


class RolesPublic(SQLModel):
    data: list[RolePublic]
    count: int


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: str | None = Field(default=None, min_length=1, max_length=255)  # type: ignore


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="app_user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# Support system models
class FaqEntryBase(SQLModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=4000)
    is_active: bool = True


class FaqEntryCreate(FaqEntryBase):
    pass


class FaqEntryUpdate(SQLModel):
    question: str | None = Field(default=None, min_length=1, max_length=500)
    answer: str | None = Field(default=None, min_length=1, max_length=4000)
    is_active: bool | None = None


class FaqEntryPublic(FaqEntryBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FaqEntriesPublic(SQLModel):
    data: list[FaqEntryPublic]
    count: int


# Таксономия базы знаний: категории (1:N) и тэги (M:N через knowledge_tag)
class KnowledgeCategory(SQLModel, table=True):
    __tablename__ = "knowledge_category"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=120)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    sources: list["KnowledgeSource"] = Relationship(back_populates="category")


class Tag(SQLModel, table=True):
    __tablename__ = "tag"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=80)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )


class KnowledgeTag(SQLModel, table=True):
    """Связь «тэг-знание» (составной PK). Связи ORM не объявлены намеренно:
    выборка тэгов делается одним запросом по списку id источников."""

    __tablename__ = "knowledge_tag"

    knowledge_id: uuid.UUID = Field(
        foreign_key="knowledge_source.id", primary_key=True, ondelete="CASCADE"
    )
    tag_id: uuid.UUID = Field(
        foreign_key="tag.id", primary_key=True, ondelete="CASCADE"
    )


class KnowledgeArchive(SQLModel, table=True):
    """Снапшот предыдущей версии знания (решения V5/V6, запись — сервисным слоем, D5).

    Удаляется вместе с источником (`ON DELETE CASCADE` — решение владельца). `category_id`
    и `tags_json` хранятся как значения без FK: снапшот должен оставаться читаемым даже
    после удаления категории или тэгов.
    """

    __tablename__ = "knowledge_archive"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_id", "version", name="uq_knowledge_archive_version"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    knowledge_id: uuid.UUID = Field(
        foreign_key="knowledge_source.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    version: int = Field(ge=1)
    title: str = Field(max_length=255)
    content: str
    category_id: uuid.UUID | None = Field(default=None)
    tags_json: list[str] = Field(default_factory=list, sa_type=JSON)
    source_type: str = Field(max_length=20)
    archived_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    archived_by: uuid.UUID | None = Field(
        default=None, foreign_key="app_user.id", nullable=True
    )


class KnowledgeArchivePublic(SQLModel):
    id: uuid.UUID
    knowledge_id: uuid.UUID
    version: int
    title: str
    content: str
    category_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list)
    source_type: str
    archived_at: datetime
    archived_by: uuid.UUID | None = None


class KnowledgeArchiveListPublic(SQLModel):
    data: list[KnowledgeArchivePublic]
    count: int


class KnowledgeSourceBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=20)
    source_ref: str | None = Field(default=None, max_length=1024)
    is_active: bool = True


class KnowledgeSourceCreate(KnowledgeSourceBase):
    content: str = Field(min_length=1)


class KnowledgeSourceUploadRequest(SQLModel):
    title: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    manual_content: str | None = None


class KnowledgeSourceUpdate(SQLModel):
    """Частичное обновление метаданных источника.

    `tags=None` — тэги не трогать, `tags=[]` — очистить набор.
    """

    title: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: uuid.UUID | None = None
    is_active: bool | None = None
    tags: list[str] | None = None


class KnowledgeSource(KnowledgeSourceBase, table=True):
    __tablename__ = "knowledge_source"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    content: str = Field(min_length=1)
    status: str = Field(default="pending", min_length=1, max_length=20)
    category_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="knowledge_category.id",
        nullable=True,
        index=True,
        ondelete="SET NULL",
    )
    last_indexed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    category: KnowledgeCategory | None = Relationship(back_populates="sources")
    chunks: list["KnowledgeChunk"] = Relationship(
        back_populates="source", cascade_delete=True
    )


class KnowledgeSourcePublic(KnowledgeSourceBase):
    id: uuid.UUID
    status: str
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    last_indexed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeSourcesPublic(SQLModel):
    data: list[KnowledgeSourcePublic]
    count: int


class KnowledgeCategoryCreate(SQLModel):
    name: str = Field(min_length=1, max_length=120)


class KnowledgeCategoryUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class KnowledgeCategoryPublic(SQLModel):
    id: uuid.UUID
    name: str
    created_at: datetime | None = None


class KnowledgeCategoriesPublic(SQLModel):
    data: list[KnowledgeCategoryPublic]
    count: int


class TagCreate(SQLModel):
    name: str = Field(min_length=1, max_length=80)


class TagPublic(SQLModel):
    id: uuid.UUID
    name: str
    created_at: datetime | None = None


class TagsPublic(SQLModel):
    data: list[TagPublic]
    count: int


class KnowledgeDoc(SQLModel, table=True):
    """Независимый корпус документов (решение V4): своей индексацией, без FK на источник."""

    __tablename__ = "knowledge_doc"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=1024)
    status: str = Field(default="pending", min_length=1, max_length=20)
    last_indexed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    chunks: list["KnowledgeChunk"] = Relationship(
        back_populates="doc", cascade_delete=True
    )


class DocTag(SQLModel, table=True):
    """Связь «тэг-док» (составной PK). ORM-связи не объявлены: тэги собираются
    одним запросом по списку id, как и для источников."""

    __tablename__ = "doc_tag"

    doc_id: uuid.UUID = Field(
        foreign_key="knowledge_doc.id", primary_key=True, ondelete="CASCADE"
    )
    tag_id: uuid.UUID = Field(
        foreign_key="tag.id", primary_key=True, ondelete="CASCADE"
    )


class KnowledgeDocBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=1024)


class KnowledgeDocCreate(KnowledgeDocBase):
    tags: list[str] = Field(default_factory=list)


class KnowledgeDocUpdate(SQLModel):
    """`tags=None` — тэги не трогать, `tags=[]` — очистить набор."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = Field(default=None, min_length=1, max_length=1024)
    tags: list[str] | None = None


class KnowledgeDocPublic(KnowledgeDocBase):
    id: uuid.UUID
    status: str
    tags: list[str] = Field(default_factory=list)
    last_indexed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeDocsPublic(SQLModel):
    data: list[KnowledgeDocPublic]
    count: int


class KnowledgeSearchRequest(SQLModel):
    """Проверка поиска по базе знаний с фильтрами (решение D4)."""

    question: str = Field(min_length=1, max_length=4000)
    owner_types: list[Literal["source", "doc"]] | None = None
    category_ids: list[uuid.UUID] | None = None
    tag_ids: list[uuid.UUID] | None = None
    limit: int = Field(default=5, ge=1, le=50)


class KnowledgeSearchHit(SQLModel):
    source_id: uuid.UUID
    source_title: str
    source_ref: str | None = None
    chunk_id: uuid.UUID | None = None
    snippet: str | None = None
    score: float


class KnowledgeSearchPublic(SQLModel):
    data: list[KnowledgeSearchHit]
    count: int


class KnowledgeChunk(SQLModel, table=True):
    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(source_id, doc_id) = 1", name="ck_knowledge_chunk_owner"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Чанк принадлежит ровно одному корпусу: источнику БЗ или документу (решение D9).
    source_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="knowledge_source.id",
        nullable=True,
        ondelete="CASCADE",
        index=True,
    )
    doc_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="knowledge_doc.id",
        nullable=True,
        ondelete="CASCADE",
        index=True,
    )
    chunk_index: int = Field(ge=0, index=True)
    content: str = Field(min_length=1)
    vector_id: str = Field(index=True, max_length=64, unique=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    source: KnowledgeSource | None = Relationship(back_populates="chunks")
    doc: KnowledgeDoc | None = Relationship(back_populates="chunks")


class SupportAskRequest(SQLModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=255)
    channel: Literal["web"] = "web"


class SourceAttribution(SQLModel):
    source_id: uuid.UUID
    source_title: str
    source_ref: str | None = None
    chunk_id: uuid.UUID | None = None
    snippet: str | None = None
    score: float | None = None


class DecisionMetrics(SQLModel):
    top_score: float = Field(default=0.0, ge=0.0, le=1.0)
    relevant_chunks: int = Field(default=0, ge=0)
    faq_score: float = Field(default=0.0, ge=0.0, le=1.0)
    conflict: bool = False
    critical: bool = False


class SupportRequest(SQLModel, table=True):
    __tablename__ = "request_journal"
    __table_args__ = (
        Index("ix_request_journal_status", "status"),
        Index("ix_request_journal_user_created", "user_id", text("created_at DESC")),
        Index("ix_request_journal_created_at", text("created_at DESC")),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Одиночного индекса по user_id нет: его роль выполняет составной
    # ix_request_journal_user_created (миграция a7c4e1b93d52).
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="app_user.id", nullable=True
    )
    session_id: str = Field(index=True, max_length=255)
    channel: str = Field(default="web", min_length=1, max_length=20)
    question: str = Field(min_length=1, max_length=4000)
    mode: str = Field(default="operator", min_length=1, max_length=20)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fallback_used: bool = False
    escalated: bool = False
    # Тема вопроса от классификатора (intent_service). None — классификатор
    # выключен, недоступен или не уверен (ниже порога из админки).
    intent: str | None = Field(default=None, max_length=50, index=True)
    intent_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Жизненный цикл: queued | in_progress | answered | closed.
    # «Активные» (queued/in_progress) дополнительно лежат в active_request — горячей таблице
    # очереди, чтобы выборка очереди не зависела от роста журнала (см. план, §0.3).
    status: str = Field(default="queued", min_length=1, max_length=20)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    answered_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    closed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    answer: "SupportAnswer" = Relationship(
        back_populates="request", cascade_delete=True
    )
    queue_item: "SupportTicket" = Relationship(
        back_populates="request", cascade_delete=True
    )
    active_state: "ActiveRequest" = Relationship(
        back_populates="request", cascade_delete=True
    )


class ActiveRequest(SQLModel, table=True):
    """Горячее рабочее множество очереди.

    Источник правды по запросам — `request_journal`, поэтому строки между таблицами
    НЕ переносятся: постановка в очередь = INSERT сюда, завершение = DELETE отсюда.
    `user_id` и `question` денормализованы сознательно: очередь читается без join
    к растущему журналу.
    """

    __tablename__ = "active_request"
    __table_args__ = (
        Index("ix_active_request_priority_queued_at", "priority", "queued_at"),
    )

    request_id: uuid.UUID = Field(
        foreign_key="request_journal.id",
        primary_key=True,
        ondelete="CASCADE",
    )
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="app_user.id", nullable=True
    )
    question: str = Field(min_length=1, max_length=4000)
    channel: str = Field(default="web", min_length=1, max_length=20)
    priority: int = Field(default=0)
    assigned_to: uuid.UUID | None = Field(
        default=None, foreign_key="app_user.id", nullable=True, index=True
    )
    queued_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    request: SupportRequest = Relationship(back_populates="active_state")


class SupportAnswer(SQLModel, table=True):
    """Запись журнала ответов: одна на шаг обработки, поэтому на запрос их может быть несколько."""

    __tablename__ = "answer_journal"
    __table_args__ = (
        UniqueConstraint("request_id", "step_index", name="uq_answer_journal_step"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="request_journal.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    # Шаг обработки: faq | rag | operator | human ("Шаг (БЗ > ИИ > агент)")
    step: str = Field(default="rag", min_length=1, max_length=20)
    step_index: int = Field(default=0, ge=0)
    performed_by: uuid.UUID | None = Field(
        default=None, foreign_key="app_user.id", nullable=True
    )
    knowledge_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="knowledge_source.id",
        nullable=True,
        ondelete="SET NULL",
    )
    knowledge_chunk_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="knowledge_chunk.id",
        nullable=True,
        ondelete="SET NULL",
    )
    answer: str = Field(min_length=1, max_length=8000)
    sources_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_type=JSON  # type: ignore
    )
    # "Завершено на данном шаге": False у автоматической эскалации, ждущей оператора.
    is_final: bool = True
    response_time_ms: int | None = Field(default=None, ge=0)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    request: "SupportRequest" = Relationship(back_populates="answer")


class SupportTicket(SQLModel, table=True):
    """Тикет поддержки: эскалация запроса оператору с возможностью переоткрытия.

    UNIQUE на `request_id` нет: переоткрытие создаёт новый тикет, ссылающийся на прежний
    через `reopened_from_id`, а одновременно активным может быть только один тикет —
    это гарантирует частичный уникальный индекс `uq_support_ticket_active` (миграция M7).
    """

    __tablename__ = "support_ticket"
    __table_args__ = (
        Index(
            "uq_support_ticket_active",
            "request_id",
            unique=True,
            postgresql_where=text("status IN ('open', 'in_progress')"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="request_journal.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    reason: str = Field(min_length=1, max_length=500)
    status: str = Field(default="open", min_length=1, max_length=20)
    assigned_to: uuid.UUID | None = Field(
        default=None, foreign_key="app_user.id", nullable=True, index=True
    )
    resolution: str | None = Field(default=None, max_length=4000)
    reopened_from_id: uuid.UUID | None = Field(
        default=None, foreign_key="support_ticket.id", nullable=True
    )
    resolved_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    request: "SupportRequest" = Relationship(back_populates="queue_item")


class SupportAskResponse(SQLModel):
    # None у отказа (mode="reject"): запись в журнале не создаётся.
    request_id: uuid.UUID | None
    session_id: str
    mode: Literal["faq", "rag", "operator", "reject"]
    answer: str
    sources: list[SourceAttribution] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    escalated: bool
    fallback_used: bool
    route_reason: str = Field(min_length=1, max_length=100)
    decision_metrics: DecisionMetrics


class SupportHistoryStep(SQLModel):
    """Шаг обработки запроса для истории (аддитивное расширение ответа /support/history)."""

    step: str
    step_index: int
    answer: str
    is_final: bool
    performed_by: uuid.UUID | None = None
    knowledge_id: uuid.UUID | None = None
    knowledge_chunk_id: uuid.UUID | None = None
    response_time_ms: int | None = None
    sources: list[SourceAttribution] = Field(default_factory=list)
    created_at: datetime | None = None


class SupportHistoryEntry(SQLModel):
    request_id: uuid.UUID
    question: str
    mode: Literal["faq", "rag", "operator"]
    answer: str
    sources: list[SourceAttribution] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    escalated: bool
    fallback_used: bool
    status: str = Field(default="completed", min_length=1, max_length=20)
    created_at: datetime | None = None
    # Чат, к которому относится обращение: по нему фронт собирает список чатов.
    session_id: str | None = None
    # Все шаги обработки, включая автоматические и (позже) ответ оператора.
    steps: list[SupportHistoryStep] = Field(default_factory=list)


class SupportHistoryPublic(SQLModel):
    data: list[SupportHistoryEntry]
    count: int


class ReindexRequest(SQLModel):
    source_ids: list[uuid.UUID] | None = None
    doc_ids: list[uuid.UUID] | None = None
    full_rebuild: bool = False
    purge_orphans: bool = True


class ReindexResponse(SQLModel):
    message: str
    reindexed_sources: int
    reindexed_docs: int = Field(default=0, ge=0)
    orphan_vectors_removed: int = Field(default=0, ge=0)
    full_rebuild: bool = False


class SupportFeedback(SQLModel, table=True):
    """Отзыв пользователя: один на запрос (решение V7)."""

    __tablename__ = "support_feedback"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_support_feedback_rating"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="request_journal.id",
        nullable=False,
        unique=True,
        ondelete="CASCADE",
        index=True,
    )
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="app_user.id", nullable=True
    )
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    submitted_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class SupportFeedbackCreate(SQLModel):
    request_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class SupportFeedbackPublic(SQLModel):
    id: uuid.UUID
    request_id: uuid.UUID
    user_id: uuid.UUID | None = None
    rating: int
    comment: str | None = None
    submitted_at: datetime


class IntentMetric(SQLModel):
    intent: str
    label: str
    total: int = Field(default=0, ge=0)
    operator_share: float = Field(default=0.0, ge=0.0, le=1.0)


class SupportMetricsPublic(SQLModel):
    total_requests: int = Field(default=0, ge=0)
    faq_share: float = Field(default=0.0, ge=0.0, le=1.0)
    rag_share: float = Field(default=0.0, ge=0.0, le=1.0)
    operator_share: float = Field(default=0.0, ge=0.0, le=1.0)
    average_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    empty_sources_share: float = Field(default=0.0, ge=0.0, le=1.0)
    # Разбивка по темам классификатора; пусто, пока он ни разу не включался.
    by_intent: list[IntentMetric] = Field(default_factory=list)
    # Отзывы: оценка по шкале 1..5, поэтому границы отличаются от долей
    feedback_count: int = Field(default=0, ge=0)
    average_rating: float = Field(default=0.0, ge=0.0, le=5.0)


class SupportTicketPublic(SQLModel):
    ticket_id: uuid.UUID
    request_id: uuid.UUID
    reason: str
    status: str
    question: str
    intent: str | None = None
    intent_label: str | None = None
    assigned_to: uuid.UUID | None = None
    resolution: str | None = None
    reopened_from_id: uuid.UUID | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None


class SupportTicketsPublic(SQLModel):
    data: list[SupportTicketPublic]
    count: int


class TicketAssignRequest(SQLModel):
    assigned_to: uuid.UUID | None = None


class TicketResolveRequest(SQLModel):
    """`resolution` — итоговое решение; оно же уходит пользователю как ответ оператора."""

    resolution: str = Field(min_length=1, max_length=4000)


class TicketReopenRequest(SQLModel):
    reason: str | None = Field(default=None, max_length=500)


# Публичные схемы очереди и журнала запросов (см. план, §0.3)
class ActiveRequestPublic(SQLModel):
    request_id: uuid.UUID
    user_id: uuid.UUID | None = None
    question: str
    channel: str
    priority: int
    assigned_to: uuid.UUID | None = None
    queued_at: datetime
    updated_at: datetime | None = None


class ActiveRequestsPublic(SQLModel):
    data: list[ActiveRequestPublic]
    count: int


class JournalRequestPublic(SQLModel):
    request_id: uuid.UUID
    user_id: uuid.UUID | None = None
    question: str
    channel: str
    mode: str
    status: str
    confidence: float
    escalated: bool
    intent: str | None = None
    intent_label: str | None = None
    intent_confidence: float | None = None
    created_at: datetime | None = None
    answered_at: datetime | None = None
    closed_at: datetime | None = None


class JournalRequestsPublic(SQLModel):
    data: list[JournalRequestPublic]
    count: int


class MyQueueEntry(SQLModel):
    queue_id: uuid.UUID
    request_id: uuid.UUID
    question: str
    reason: str
    status: str
    created_at: datetime | None = None
    reply_text: str | None = None
    reply_created_at: datetime | None = None


class MyQueuePublic(SQLModel):
    data: list[MyQueueEntry]
    count: int


# --------------------------- внешние RAG-движки ---------------------------

RagProviderName = Literal["legacy", "search_only", "gemini_file_search", "anythingllm"]
IngestTarget = Literal["gemini", "anythingllm", "both", "local"]


class AppSetting(SQLModel, table=True):
    """Настройки, которые админ меняет на лету (например, активный RAG-движок).

    Хранятся в БД, а не в памяти процесса: backend работает в нескольких воркерах.
    """

    __tablename__ = "app_setting"

    key: str = Field(primary_key=True, max_length=100)
    value: str = Field(max_length=1000)
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class IngestJob(SQLModel, table=True):
    """Пакетная загрузка файлов во внешние движки (Gemini / AnythingLLM)."""

    __tablename__ = "ingest_job"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    target: str = Field(max_length=20)
    total: int = Field(ge=1)
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="app_user.id", nullable=True, ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class IngestItem(SQLModel, table=True):
    """Один файл пакета: статус по каждому движку и ошибка, если была."""

    __tablename__ = "ingest_item"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(
        foreign_key="ingest_job.id", nullable=False, ondelete="CASCADE", index=True
    )
    filename: str = Field(max_length=500)
    size_bytes: int = 0
    # queued -> running -> done | failed
    status: str = Field(default="queued", max_length=20, index=True)
    # ok | already | no-text | error | None (движок не выбран)
    gemini_status: str | None = Field(default=None, max_length=20)
    anythingllm_status: str | None = Field(default=None, max_length=20)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    started_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    finished_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )


class RagProviderOption(SQLModel):
    name: str
    label: str
    configured: bool


class RagProviderPublic(SQLModel):
    active: str
    default: str
    options: list[RagProviderOption]


class RagProviderUpdate(SQLModel):
    provider: RagProviderName


class IngestJobCreate(SQLModel):
    target: IngestTarget
    total: int = Field(ge=1, le=1000)


class IngestItemPublic(SQLModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    status: str
    gemini_status: str | None = None
    anythingllm_status: str | None = None
    # Встроенная база знаний (Postgres): своей колонки нет, выводится из status.
    local_status: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class IngestJobPublic(SQLModel):
    id: uuid.UUID
    target: str
    total: int
    uploaded: int
    done: int
    failed: int
    finished: bool
    eta_seconds: int | None = None
    created_at: datetime
    items: list[IngestItemPublic] = []


class IngestJobsPublic(SQLModel):
    data: list[IngestJobPublic]
    count: int


class EngineDocument(SQLModel):
    name: str
    state: str | None = None
    size_bytes: int | None = None


class EngineDocumentsPublic(SQLModel):
    engine: str
    configured: bool
    error: str | None = None
    data: list[EngineDocument]
    count: int


# --------------------------- классификатор тем ---------------------------


class IntentCategoryPublic(SQLModel):
    name: str
    label: str


class IntentStatusPublic(SQLModel):
    enabled: bool
    threshold: float = Field(ge=0.0, le=1.0)
    service_url: str
    # Ответил ли сервис на /health и загружена ли в нём модель.
    reachable: bool = False
    model_loaded: bool = False
    error: str | None = None
    categories: list[IntentCategoryPublic] = Field(default_factory=list)


class IntentTestRequest(SQLModel):
    question: str = Field(min_length=1, max_length=4000)


class IntentCandidatePublic(SQLModel):
    category: str
    label: str
    confidence: float


class IntentTestPublic(SQLModel):
    # None, когда уверенность ниже порога: так тема и не запишется в журнал.
    intent: str | None = None
    intent_label: str | None = None
    confidence: float = 0.0
    threshold: float
    candidates: list[IntentCandidatePublic] = Field(default_factory=list)
    error: str | None = None
