import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import EmailStr
from sqlalchemy import JSON, DateTime
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


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
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
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


class FaqEntry(FaqEntryBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    normalized_question: str = Field(index=True, max_length=500)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )


class FaqEntryPublic(FaqEntryBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FaqEntriesPublic(SQLModel):
    data: list[FaqEntryPublic]
    count: int


class KnowledgeSourceBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=20)
    source_ref: str | None = Field(default=None, max_length=1024)
    is_active: bool = True


class KnowledgeSourceCreate(KnowledgeSourceBase):
    content: str = Field(min_length=1)


class KnowledgeSource(KnowledgeSourceBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    content: str = Field(min_length=1)
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
        back_populates="source", cascade_delete=True
    )


class KnowledgeSourcePublic(KnowledgeSourceBase):
    id: uuid.UUID
    status: str
    last_indexed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeSourcesPublic(SQLModel):
    data: list[KnowledgeSourcePublic]
    count: int


class KnowledgeChunk(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_id: uuid.UUID = Field(
        foreign_key="knowledgesource.id", nullable=False, ondelete="CASCADE", index=True
    )
    chunk_index: int = Field(ge=0, index=True)
    content: str = Field(min_length=1)
    vector_id: str = Field(index=True, max_length=64, unique=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    source: KnowledgeSource | None = Relationship(back_populates="chunks")


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


class SupportRequest(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, index=True
    )
    session_id: str = Field(index=True, max_length=255)
    channel: str = Field(default="web", min_length=1, max_length=20)
    question: str = Field(min_length=1, max_length=4000)
    mode: str = Field(default="operator", min_length=1, max_length=20)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fallback_used: bool = False
    escalated: bool = False
    status: str = Field(default="completed", min_length=1, max_length=20)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    answer: "SupportAnswer" = Relationship(
        back_populates="request", cascade_delete=True
    )
    queue_item: "OperatorQueue" = Relationship(
        back_populates="request", cascade_delete=True
    )


class SupportAnswer(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="supportrequest.id",
        nullable=False,
        unique=True,
        ondelete="CASCADE",
        index=True,
    )
    answer: str = Field(min_length=1, max_length=8000)
    sources_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_type=JSON  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    request: "SupportRequest" = Relationship(back_populates="answer")


class OperatorQueue(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="supportrequest.id",
        nullable=False,
        unique=True,
        ondelete="CASCADE",
        index=True,
    )
    reason: str = Field(min_length=1, max_length=500)
    status: str = Field(default="open", min_length=1, max_length=20)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )
    request: "SupportRequest" = Relationship(back_populates="queue_item")


class SupportAskResponse(SQLModel):
    request_id: uuid.UUID
    session_id: str
    mode: Literal["faq", "rag", "operator"]
    answer: str
    sources: list[SourceAttribution] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    escalated: bool
    fallback_used: bool


class SupportHistoryEntry(SQLModel):
    request_id: uuid.UUID
    question: str
    mode: Literal["faq", "rag", "operator"]
    answer: str
    sources: list[SourceAttribution] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    escalated: bool
    fallback_used: bool
    created_at: datetime | None = None


class SupportHistoryPublic(SQLModel):
    data: list[SupportHistoryEntry]
    count: int


class ReindexRequest(SQLModel):
    source_ids: list[uuid.UUID] | None = None


class ReindexResponse(SQLModel):
    message: str
    reindexed_sources: int


class OperatorQueueEntry(SQLModel):
    queue_id: uuid.UUID
    request_id: uuid.UUID
    reason: str
    status: str
    question: str
    created_at: datetime | None = None


class OperatorQueuePublic(SQLModel):
    data: list[OperatorQueueEntry]
    count: int
