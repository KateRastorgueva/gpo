import { Briefcase, Headset, Home, Settings2, Users } from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import usePermissions from "@/hooks/usePermissions"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "Dashboard", path: "/" },
  { icon: Briefcase, title: "Items", path: "/items" },
  { icon: Headset, title: "Support", path: "/support" },
]

export function AppSidebar() {
  const {
    user: currentUser,
    canOpenSupportAdmin,
    canManageUsers,
  } = usePermissions()

  // Разделы появляются по правам роли: оператор видит работу с обращениями,
  // но не управление пользователями, обычный пользователь — только базовые разделы.
  const items: Item[] = [
    ...baseItems,
    ...(canOpenSupportAdmin
      ? [
          {
            icon: Settings2,
            title: "Support Admin",
            path: "/admin-support",
          } satisfies Item,
        ]
      : []),
    ...(canManageUsers
      ? [{ icon: Users, title: "Admin", path: "/admin" } satisfies Item]
      : []),
  ]

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
