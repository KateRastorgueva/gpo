import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"

import {
  EmptyState,
  formatDateTime,
  StatusBadge,
} from "@/components/Support/display"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getOperatorQueue } from "@/services/supportApi"

const ACTIVE_STATUSES = ["open", "in_progress"]

/**
 * Список тикетов. Переписка открывается на отдельной странице /ticket/<id> —
 * большом чате оператора (см. TicketChatPage).
 */
export function TicketsPanel() {
  const ticketsQuery = useQuery({
    queryKey: ["adminTickets"],
    queryFn: getOperatorQueue,
  })

  const tickets = ticketsQuery.data?.data ?? []
  const activeCount = tickets.filter((ticket) =>
    ACTIVE_STATUSES.includes(ticket.status),
  ).length

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Тикеты</CardTitle>
        <span className="text-xs text-muted-foreground">
          {activeCount} активных из {tickets.length}
        </span>
      </CardHeader>
      <CardContent className="grid gap-3">
        {ticketsQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Загрузка тикетов...</p>
        ) : null}
        {!ticketsQuery.isPending && tickets.length === 0 ? (
          <EmptyState text="Тикетов нет: все запросы закрыты автоматически." />
        ) : null}

        {tickets.map((ticket) => (
          <div
            key={ticket.ticket_id}
            data-testid="ticket-card"
            className="grid gap-2 rounded-lg border p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={ticket.status} />
              {ticket.intent_label ? (
                <span className="rounded-md bg-muted px-2 py-0.5 text-xs">
                  {ticket.intent_label}
                </span>
              ) : null}
              {ticket.reopened_from_id ? (
                <span className="text-xs text-muted-foreground">
                  переоткрыт
                </span>
              ) : null}
              <span className="ml-auto text-xs text-muted-foreground">
                {formatDateTime(ticket.created_at)}
              </span>
            </div>
            <p className="text-sm font-medium">{ticket.question}</p>
            <p className="text-xs text-muted-foreground">
              Причина эскалации: {ticket.reason}
            </p>
            <div>
              <Link to="/ticket/$ticketId" params={{ ticketId: ticket.ticket_id }}>
                <Button size="sm">Открыть переписку</Button>
              </Link>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
