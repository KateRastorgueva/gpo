import { createFileRoute, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { sectionPath, sectionsFor } from "@/components/SupportAdmin/sections"

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
    const [section] = sectionsFor(user)
    throw redirect({ to: section ? sectionPath(section) : "/support" })
  },
  component: () => null,
  head: () => ({
    meta: [{ title: "Техподдержка ТУСУР" }],
  }),
})
