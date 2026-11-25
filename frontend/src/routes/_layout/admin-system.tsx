import { createFileRoute, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { AdminSectionPage } from "@/components/SupportAdmin/AdminSectionPage"
import { findSection } from "@/components/SupportAdmin/sections"
import { hasPermission } from "@/lib/permissions"

const SECTION = findSection("system")

export const Route = createFileRoute("/_layout/admin-system")({
  component: () => (SECTION ? <AdminSectionPage section={SECTION} /> : null),
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    // Раздел открыт, если доступна хотя бы одна его подвкладка.
    if (
      !SECTION ||
      !SECTION.children.some((child) => hasPermission(user, child.permission))
    ) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({ meta: [{ title: SECTION?.label ?? "Система" }] }),
})
