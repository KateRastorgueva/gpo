from fastapi import APIRouter

from app.api.routes import admin_support, items, login, private, support, users, utils
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(support.router)
api_router.include_router(admin_support.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
