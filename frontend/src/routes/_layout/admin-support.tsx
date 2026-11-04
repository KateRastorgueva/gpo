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

type TabDefinition = {
  value: string
  label: string
  permission: Permission
  render: () => React.ReactNode
}

// Вкладки объявляются вместе с правом, которое их открывает:
// оператор видит метрики и обращения, админ — ещё и редактирование знаний.
const TABS: TabDefinition[] = [
  {
    value: "metrics",
    label: "Метрики",
    permission: PERMISSIONS.METRICS_READ,
    render: () => <MetricsPanel />,
  },
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
  {
    value: "knowledge",
    label: "База знаний",
    permission: PERMISSIONS.KNOWLEDGE_READ,
    render: () => <KnowledgePanel />,
  },
  {
    value: "docs",
    label: "Документы",
    permission: PERMISSIONS.KNOWLEDGE_READ,
    render: () => <DocsPanel />,
  },
  {
    value: "engines",
    label: "Движки RAG",
    permission: PERMISSIONS.KNOWLEDGE_READ,
    render: () => <EnginesPanel />,
  },
  {
    value: "taxonomy",
    label: "Категории и тэги",
    permission: PERMISSIONS.KNOWLEDGE_READ,
    render: () => <TaxonomyPanel />,
  },
  {
    value: "search",
    label: "Поиск",
    permission: PERMISSIONS.KNOWLEDGE_READ,
    render: () => <SearchPanel />,
  },
  {
    value: "faq",
    label: "Частые вопросы",
    permission: PERMISSIONS.KNOWLEDGE_READ,
    render: () => <FaqPanel />,
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
  {
    value: "settings",
    label: "Настройки",
    permission: PERMISSIONS.SETTINGS_MANAGE,
    render: () => <SettingsPanel />,
  },
]

function AdminSupportPage() {
  const { has, roleName, isLoading } = usePermissions()
  const [selectedTab, setSelectedTab] = useState<string | undefined>(undefined)
  const availableTabs = TABS.filter((tab) => has(tab.permission))

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
            {tab.render()}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
