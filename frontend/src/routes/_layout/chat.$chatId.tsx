import { createFileRoute } from "@tanstack/react-router"

import { SupportPage } from "@/components/Support/SupportPage"

/** Ссылка на конкретный чат: /chat/<session_id>. */
export const Route = createFileRoute("/_layout/chat/$chatId")({
  component: ChatPage,
  head: () => ({
    meta: [{ title: "Чат поддержки ТУСУР" }],
  }),
})

function ChatPage() {
  const { chatId } = Route.useParams()
  return <SupportPage initialChatId={chatId} />
}
