import { useQuery } from "@tanstack/react-query"

import { type UserPublic, UsersService } from "@/client"
import {
  canManageUsers,
  canOpenSupportAdmin,
  hasAnyPermission,
  hasPermission,
  type Permission,
} from "@/lib/permissions"

/**
 * Текущий пользователь вместе с проверками прав.
 *
 * Использует тот же queryKey, что и `useAuth`, поэтому данные берутся из кэша
 * без дополнительного запроса.
 */
export const usePermissions = () => {
  const { data: user, isLoading } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: UsersService.readUserMe,
    enabled: localStorage.getItem("access_token") !== null,
  })

  return {
    user,
    isLoading,
    permissions: user?.permissions ?? [],
    roleName: user?.role_name ?? null,
    has: (permission: Permission) => hasPermission(user, permission),
    hasAny: (permissions: Permission[]) => hasAnyPermission(user, permissions),
    canOpenSupportAdmin: canOpenSupportAdmin(user),
    canManageUsers: canManageUsers(user),
  }
}

export type UsePermissionsResult = ReturnType<typeof usePermissions>

export default usePermissions
