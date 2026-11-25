import { createFileRoute, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { canOpenSupportAdmin } from "@/lib/permissions"

export const Route = createFileRoute("/_layout/")({
  // Отдельной «Главной» нет: после входа каждый попадает в свой основной раздел —
  // админ и оператор в «Управление», обычный пользователь в чат поддержки.
  beforeLoad: async () => {
    let user = null
    try {
      user = await UsersService.readUserMe()
    } catch {
      user = null
    }
    throw redirect({
      to: canOpenSupportAdmin(user) ? "/admin-support" : "/support",
    })
  },
  component: () => null,
  head: () => ({
    meta: [{ title: "Техподдержка ТУСУР" }],
  }),
})
