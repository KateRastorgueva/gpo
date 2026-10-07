import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.permissions import DEFAULT_ROLE_NAME
from app.core.security import get_password_hash, verify_password
from app.models import Item, ItemCreate, Role, User, UserCreate, UserUpdate


def get_role_by_name(*, session: Session, name: str) -> Role | None:
    statement = select(Role).where(Role.name == name)
    return session.exec(statement).first()


def get_default_role(session: Session) -> Role:
    """Роль по умолчанию для новых пользователей.

    Роли создаются миграцией `c5a9e3d1b746_roles_and_permissions`, поэтому отсутствие
    роли означает, что схема не догнана до head.
    """
    role = get_role_by_name(session=session, name=DEFAULT_ROLE_NAME)
    if role is None:
        raise RuntimeError(
            f"Default role {DEFAULT_ROLE_NAME!r} is missing: "
            "run `alembic upgrade head` to seed roles before creating users."
        )
    return role


def assign_role(*, session: Session, user: User, role: Role) -> User:
    user.role_id = role.id
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def create_user(*, session: Session, user_create: UserCreate) -> User:
    # Роль из запроса важнее роли по умолчанию; существование проверяет роутер.
    role_id = user_create.role_id or get_default_role(session).id
    db_obj = User.model_validate(
        user_create,
        update={
            "hashed_password": get_password_hash(user_create.password),
            "role_id": role_id,
        },
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item
