import { createFileRoute, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { sectionPath, sectionsFor } from "@/components/SupportAdmin/sections"

/**
 * Старый адрес «Управления». Раньше здесь были вкладки, теперь разделы вынесены
 * в левое меню — оставляем редирект, чтобы не ломать закладки.
 */
export const Route = createFileRoute("/_layout/admin-support")({
  component: () => null,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    const [section] = sectionsFor(user)
    throw redirect({ to: section ? sectionPath(section) : "/" })
  },
  head: () => ({ meta: [{ title: "Управление" }] }),
})
