"""Каталог разрешений и матрица ролей (RBAC).

Модуль — источник правды по правам во время выполнения. Матрица ролей дополнительно
зашита в миграции `c5a9e3d1b746_roles_and_permissions`: миграция должна быть
самодостаточной и не зависеть от кода приложения. Поэтому при изменении матрицы
нужна отдельная миграция синхронизации существующих ролей.
"""

from app.models import PERMISSION_WILDCARD, Role, User

# Wildcard: роль с этим правом получает доступ ко всему. Раскрывается внутри
# has_permission, поэтому в require_permission("*") передавать не нужно.
WILDCARD = PERMISSION_WILDCARD

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_USER = "user"

DEFAULT_ROLE_NAME = ROLE_USER

KNOWLEDGE_READ = "knowledge:read"
KNOWLEDGE_WRITE = "knowledge:write"
TICKET_READ = "ticket:read"
TICKET_RESOLVE = "ticket:resolve"
METRICS_READ = "metrics:read"
USER_MANAGE = "user:manage"
TAXONOMY_WRITE = "taxonomy:write"

ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        KNOWLEDGE_READ,
        KNOWLEDGE_WRITE,
        TICKET_READ,
        TICKET_RESOLVE,
        METRICS_READ,
        USER_MANAGE,
        TAXONOMY_WRITE,
    }
)

ROLE_PERMISSIONS: dict[str, list[str]] = {
    ROLE_ADMIN: [WILDCARD],
    ROLE_OPERATOR: [KNOWLEDGE_READ, TICKET_READ, TICKET_RESOLVE, METRICS_READ],
    ROLE_USER: [],
}


def has_permission(user: User, permission: str) -> bool:
    """Проверить, что роль пользователя даёт указанное разрешение."""
    role: Role | None = user.role
    if role is None:
        return False
    permissions = role.permissions or []
    return WILDCARD in permissions or permission in permissions
