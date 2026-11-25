import { createFileRoute, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { TicketsPanel } from "@/components/SupportAdmin/TicketsPanel"
import { hasPermission, PERMISSIONS } from "@/lib/permissions"

/** Ссылка на конкретный тикет: /ticket/<ticket_id> — переписка открыта сразу. */
export const Route = createFileRoute("/_layout/ticket/$ticketId")({
  component: TicketPage,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!hasPermission(user, PERMISSIONS.TICKET_READ)) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({
    meta: [{ title: "Тикет" }],
  }),
})

function TicketPage() {
  const { ticketId } = Route.useParams()
  return (
    <div className="mx-auto grid w-full min-w-0 max-w-6xl grid-cols-1 gap-4">
      <h1 className="text-2xl font-semibold">Тикет</h1>
      <TicketsPanel initialTicketId={ticketId} />
    </div>
  )
}
