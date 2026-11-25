import { BarChart3, BookOpen, Inbox, type LucideIcon, Settings2 } from "lucide-react"
import type { ReactNode } from "react"

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
import { hasPermission, PERMISSIONS, type Permission } from "@/lib/permissions"
import type { UserPublic } from "@/client"

/**
 * Админ-разделы: каждый — отдельная страница и пункт левого меню.
 * Внутри раздела — подвкладки, объявленные вместе с правом, которое их открывает.
 */

export type AdminSubTab = {
  value: string
  label: string
  permission: Permission
  render: () => ReactNode
}

export type AdminSection = {
  /** Слаг в адресе: /admin-<slug> */
  value: string
  label: string
  icon: LucideIcon
  children: AdminSubTab[]
}

export const ADMIN_SECTIONS: AdminSection[] = [
  {
    value: "requests",
    label: "Тикеты",
    icon: Inbox,
    children: [
      {
        value: "tickets",
        label: "Тикеты",
        permission: PERMISSIONS.TICKET_READ,
        render: () => <TicketsPanel />,
      },
      {
        value: "queue",
        label: "Очередь и журнал",
        permission: PERMISSIONS.TICKET_READ,
        render: () => <RequestsPanel />,
      },
    ],
  },
  {
    value: "knowledge",
    label: "Знания",
    icon: BookOpen,
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
    value: "metrics",
    label: "Метрики",
    icon: BarChart3,
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
    icon: Settings2,
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

/** Адрес страницы раздела. */
export const sectionPath = (section: AdminSection) => `/admin-${section.value}`

/** Раздел по слагу (для маршрутов). */
export const findSection = (slug: string) =>
  ADMIN_SECTIONS.find((section) => section.value === slug)

/** Разделы, доступные пользователю (хотя бы одна подвкладка). */
export const sectionsFor = (user: UserPublic | null | undefined) =>
  ADMIN_SECTIONS.filter((section) =>
    section.children.some((child) => hasPermission(user, child.permission)),
  )
