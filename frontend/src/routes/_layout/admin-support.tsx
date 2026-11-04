import { createFileRoute, redirect } from "@tanstack/react-router"
import { useState } from "react"

import { UsersService } from "@/client"
import { BuildVersion } from "@/components/Common/BuildVersion"
import { DocsPanel } from "@/components/SupportAdmin/DocsPanel"
import { EnginesPanel } from "@/components/SupportAdmin/EnginesPanel"
import { FaqPanel } from "@/components/SupportAdmin/FaqPanel"
import { IntentPanel } from "@/components/SupportAdmin/IntentPanel"
import { KnowledgePanel } from "@/components/SupportAdmin/KnowledgePanel"
import { MetricsPanel } from "@/components/SupportAdmin/MetricsPanel"
import { RequestsPanel } from "@/components/SupportAdmin/RequestsPanel"
import { SearchPanel } from "@/components/SupportAdmin/SearchPanel"
import { SettingsPanel } from "@/components/SupportAdmin/SettingsPanel"
import { TaxonomyPanel } from "@/components/SupportAdmin/TaxonomyPanel"
import { TicketsPanel } from "@/components/SupportAdmin/TicketsPanel"
import { UsersPanel } from "@/components/SupportAdmin/UsersPanel"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import usePermissions from "@/hooks/usePermissions"
import {
  canOpenSupportAdmin,
  PERMISSIONS,
  type Permission,
} from "@/lib/permissions"

export const Route = createFileRoute("/_layout/admin-support")({
  component: AdminSupportPage,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    // Раздел нужен всем, у кого есть доступ хотя бы к одной его вкладке
    if (!canOpenSupportAdmin(user)) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({
    meta: [{ title: "Управление" }],
  }),
})

type SubTab = {
  value: string
  label: string
  permission: Permission
  render: () => React.ReactNode
}

type TabDefinition = {
  value: string
  label: string
  // Раздел показан, если доступна хотя бы одна его подвкладка
  children: SubTab[]
}

// Разделы сгруппированы по задачам работы, а не по техническим сущностям.
// Подвкладка объявляется вместе с правом, которое её открывает.
const TABS: TabDefinition[] = [
  {
    value: "knowledge",
    label: "Знания",
    children: [
      {
        value: "docs",
        label: "Документы",
        permission: PERMISSIONS.KNOWLEDGE_READ,
        render: () => <DocsPanel />,
      },
      {
        value: "sources",
        label: "Источники",
        permission: PERMISSIONS.KNOWLEDGE_READ,
        render: () => <KnowledgePanel />,
      },
      {
        value: "engines",
        label: "Движок",
        permission: PERMISSIONS.KNOWLEDGE_READ,
        render: () => <EnginesPanel />,
      },
      {
        value: "search",
        label: "Проверка поиска",
        permission: PERMISSIONS.KNOWLEDGE_READ,
        render: () => <SearchPanel />,
      },
      {
        value: "taxonomy",
        label: "Категории и тэги",
        permission: PERMISSIONS.KNOWLEDGE_READ,
        render: () => <TaxonomyPanel />,
      },
      {
        value: "faq",
        label: "Частые вопросы",
        permission: PERMISSIONS.KNOWLEDGE_READ,
        render: () => <FaqPanel />,
      },
    ],
  },
  {
    value: "tickets",
    label: "Обращения",
    children: [
      {
        value: "requests",
        label: "Очередь и журнал",
        permission: PERMISSIONS.TICKET_READ,
        render: () => <RequestsPanel />,
      },
      {
        value: "tickets",
        label: "Тикеты",
        permission: PERMISSIONS.TICKET_READ,
        render: () => <TicketsPanel />,
      },
    ],
  },
  {
    value: "metrics",
    label: "Метрики",
    children: [
      {
        value: "metrics",
        label: "Метрики",
        permission: PERMISSIONS.METRICS_READ,
        render: () => <MetricsPanel />,
      },
    ],
  },
  {
    value: "system",
    label: "Система",
    children: [
      {
        value: "settings",
        label: "Настройки",
        permission: PERMISSIONS.SETTINGS_MANAGE,
        render: () => <SettingsPanel />,
      },
      {
        value: "intent",
        label: "Классификатор тем",
        permission: PERMISSIONS.METRICS_READ,
        render: () => <IntentPanel />,
      },
      {
        value: "users",
        label: "Пользователи",
        permission: PERMISSIONS.USER_MANAGE,
        render: () => <UsersPanel />,
      },
    ],
  },
]

function Section({ children }: { children: SubTab[] }) {
  const [selected, setSelected] = useState<string | undefined>(undefined)
  const active = children.some((child) => child.value === selected)
    ? selected
    : children[0]?.value

  // Единственная подвкладка (например, «Метрики») не нуждается в переключателе
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

function AdminSupportPage() {
  const { has, roleName, isLoading } = usePermissions()
  const [selectedTab, setSelectedTab] = useState<string | undefined>(undefined)
  const availableTabs = TABS.map((tab) => ({
    ...tab,
    children: tab.children.filter((child) => has(child.permission)),
  })).filter((tab) => tab.children.length > 0)

  // Вкладка вычисляется из доступных: права приходят запросом, и с defaultValue
  // страница осталась бы пустой, пока список вкладок не загрузился.
  const activeTab = availableTabs.some((tab) => tab.value === selectedTab)
    ? selectedTab
    : availableTabs[0]?.value

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">Загрузка прав доступа...</p>
    )
  }

  return (
    <div className="mx-auto grid w-full min-w-0 max-w-6xl grid-cols-1 gap-6">
      <div>
        <h1 className="text-2xl font-semibold">Управление</h1>
        <p className="text-sm text-muted-foreground">
          Роль: {roleName ?? "не задана"} — разделы и действия показаны по вашим
          правам.
        </p>
        <BuildVersion className="mt-1" />
      </div>

      <Tabs
        value={activeTab}
        onValueChange={setSelectedTab}
        className="grid min-w-0 grid-cols-1 gap-4"
      >
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1">
          {availableTabs.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              // Без этого первая строка вкладок растягивается на всю высоту
              // списка, а вторая уезжает под содержимое и не кликается.
              className="h-8 flex-none"
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {availableTabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value} className="min-w-0">
            <Section>{tab.children}</Section>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
