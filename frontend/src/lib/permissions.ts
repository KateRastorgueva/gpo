import type { UserPublic } from "@/client"

/**
 * Права доступа: те же строки, что и в backend (`app/core/permissions.py`).
 * UI по ним решает, какие разделы и действия показывать.
 */
export const WILDCARD = "*"

export const PERMISSIONS = {
  KNOWLEDGE_READ: "knowledge:read",
  KNOWLEDGE_WRITE: "knowledge:write",
  TICKET_READ: "ticket:read",
  TICKET_RESOLVE: "ticket:resolve",
  METRICS_READ: "metrics:read",
  USER_MANAGE: "user:manage",
  TAXONOMY_WRITE: "taxonomy:write",
} as const

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]

type UserLike = Pick<UserPublic, "permissions"> | null | undefined

export const hasPermission = (
  user: UserLike,
  permission: Permission,
): boolean => {
  const permissions = user?.permissions ?? []
  return permissions.includes(WILDCARD) || permissions.includes(permission)
}

export const hasAnyPermission = (
  user: UserLike,
  permissions: Permission[],
): boolean => permissions.some((permission) => hasPermission(user, permission))

/** Раздел «Администрирование поддержки» нужен тем, у кого есть хоть один доступ в нём. */
export const SUPPORT_ADMIN_PERMISSIONS: Permission[] = [
  PERMISSIONS.METRICS_READ,
  PERMISSIONS.TICKET_READ,
  PERMISSIONS.KNOWLEDGE_READ,
  PERMISSIONS.USER_MANAGE,
]

export const canOpenSupportAdmin = (user: UserLike) =>
  hasAnyPermission(user, SUPPORT_ADMIN_PERMISSIONS)

/** Управление пользователями доступно только с `user:manage`. */
export const canManageUsers = (user: UserLike) =>
  hasPermission(user, PERMISSIONS.USER_MANAGE)
