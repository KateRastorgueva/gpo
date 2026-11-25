import { Headset } from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import { sectionPath, sectionsFor } from "@/components/SupportAdmin/sections"
import usePermissions from "@/hooks/usePermissions"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Headset, title: "Чат", path: "/support" },
]

export function AppSidebar() {
  const { user: currentUser } = usePermissions()

  // Оператор и админ работают в админ-разделах (первый — «Тикеты»), а не в
  // пользовательском чате; обычный пользователь видит только «Чат».
  const sections = sectionsFor(currentUser)
  const items: Item[] =
    sections.length > 0
      ? sections.map(
          (section) =>
            ({
              icon: section.icon,
              title: section.label,
              path: sectionPath(section),
            }) satisfies Item,
        )
      : baseItems

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
