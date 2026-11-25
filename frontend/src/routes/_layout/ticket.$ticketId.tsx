import { createFileRoute, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { TicketChatPage } from "@/components/SupportAdmin/TicketChatPage"
import { hasPermission, PERMISSIONS } from "@/lib/permissions"

/** Чат оператора с пользователем: /ticket/<ticket_id> (слева список тикетов). */
export const Route = createFileRoute("/_layout/ticket/$ticketId")({
  component: TicketPage,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!hasPermission(user, PERMISSIONS.TICKET_READ)) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({
    meta: [{ title: "Переписка по тикету" }],
  }),
})

function TicketPage() {
  const { ticketId } = Route.useParams()
  return <TicketChatPage ticketId={ticketId} />
}
