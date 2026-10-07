from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.core.permissions import ROLE_ADMIN
from app.models import User, UserCreate

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
        )
        # Роль по умолчанию назначается в crud, поэтому первый пользователь
        # дополнительно повышается до администратора ниже.
        user = crud.create_user(session=session, user_create=user_in)

    admin_role = crud.get_role_by_name(session=session, name=ROLE_ADMIN)
    if admin_role is None:
        raise RuntimeError(
            f"Role {ROLE_ADMIN!r} is missing: "
            "run `alembic upgrade head` to seed roles before creating initial data."
        )
    if user.role_id != admin_role.id:
        user = crud.assign_role(session=session, user=user, role=admin_role)
