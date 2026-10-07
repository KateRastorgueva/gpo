import { useQuery } from "@tanstack/react-query"

import { UsersService } from "@/client"

/** Справочник ролей для админки: права определяет роль, а не флаг is_superuser. */
export const useRoles = () =>
  useQuery({
    queryKey: ["roles"],
    queryFn: () => UsersService.readRoles(),
    staleTime: 5 * 60 * 1000,
  })
