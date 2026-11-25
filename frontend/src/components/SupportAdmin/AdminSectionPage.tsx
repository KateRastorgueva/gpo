import { useState } from "react"

import { BuildVersion } from "@/components/Common/BuildVersion"
import type { AdminSection, AdminSubTab } from "@/components/SupportAdmin/sections"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import usePermissions from "@/hooks/usePermissions"

/** Подвкладки раздела: единственная подвкладка рендерится без переключателя. */
function SubTabs({ children }: { children: AdminSubTab[] }) {
  const [selected, setSelected] = useState<string | undefined>(undefined)
  const active = children.some((child) => child.value === selected)
    ? selected
    : children[0]?.value

  if (children.length === 1) return <>{children[0].render()}</>

  return (
    <Tabs
      value={active}
      onValueChange={setSelected}
      className="grid min-w-0 grid-cols-1 gap-4"
    >
      <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1">
        {children.map((child) => (
          <TabsTrigger
            key={child.value}
            value={child.value}
            className="h-8 flex-none"
          >
            {child.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {children.map((child) => (
        <TabsContent key={child.value} value={child.value} className="min-w-0">
          {child.render()}
        </TabsContent>
      ))}
    </Tabs>
  )
}

/** Страница админ-раздела: заголовок, роль и подвкладки по правам. */
export function AdminSectionPage({ section }: { section: AdminSection }) {
  const { has, roleName, isLoading } = usePermissions()
  const children = section.children.filter((child) => has(child.permission))

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">Загрузка прав доступа...</p>
    )
  }

  return (
    <div className="mx-auto grid w-full min-w-0 max-w-6xl grid-cols-1 gap-6">
      <div>
        <h1 className="text-2xl font-semibold">{section.label}</h1>
        <p className="text-sm text-muted-foreground">
          Роль: {roleName ?? "не задана"} — разделы и действия показаны по вашим
          правам.
        </p>
        <BuildVersion className="mt-1" />
      </div>
      {children.length ? (
        <SubTabs>{children}</SubTabs>
      ) : (
        <p className="text-sm text-muted-foreground">
          Нет доступа ни к одной вкладке этого раздела.
        </p>
      )}
    </div>
  )
}
