import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { UsersService } from "@/client"
import {
  EmptyState,
  formatDateTime,
  StatusBadge,
} from "@/components/Support/display"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import usePermissions from "@/hooks/usePermissions"
import { PERMISSIONS } from "@/lib/permissions"
import {
  assignTicket,
  getOperatorQueue,
  reopenTicket,
  resolveTicket,
  type SupportTicket,
} from "@/services/supportApi"

const ACTIVE_STATUSES = ["open", "in_progress"]

export function TicketsPanel() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { has } = usePermissions()
  // Без ticket:resolve тикеты доступны только на чтение
  const canResolve = has(PERMISSIONS.TICKET_RESOLVE)
  const queryClient = useQueryClient()
  const [resolveTarget, setResolveTarget] = useState<SupportTicket | null>(null)
  const [reopenTarget, setReopenTarget] = useState<SupportTicket | null>(null)
  const [resolution, setResolution] = useState("")
  const [reopenReason, setReopenReason] = useState("")

  const ticketsQuery = useQuery({
    queryKey: ["adminTickets"],
    queryFn: getOperatorQueue,
  })
  const meQuery = useQuery({
    queryKey: ["currentUser"],
    queryFn: () => UsersService.readUserMe(),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["adminTickets"] })
    queryClient.invalidateQueries({ queryKey: ["adminActiveRequests"] })
    queryClient.invalidateQueries({ queryKey: ["adminJournalRequests"] })
    queryClient.invalidateQueries({ queryKey: ["adminSupportMetrics"] })
  }

  const assignMutation = useMutation({
    mutationFn: (ticketId: string) =>
      assignTicket(ticketId, meQuery.data?.id ?? null),
    onSuccess: () => {
      showSuccessToast("Тикет назначен на вас")
      refresh()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const resolveMutation = useMutation({
    mutationFn: (ticketId: string) =>
      resolveTicket(ticketId, resolution.trim()),
    onSuccess: () => {
      showSuccessToast("Ответ оператора сохранён, запрос закрыт")
      setResolveTarget(null)
      setResolution("")
      refresh()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const reopenMutation = useMutation({
    mutationFn: (ticketId: string) =>
      reopenTicket(ticketId, reopenReason.trim() || undefined),
    onSuccess: () => {
      showSuccessToast("Тикет переоткрыт, запрос вернулся в очередь")
      setReopenTarget(null)
      setReopenReason("")
      refresh()
    },
    onError: (error: Error) => showErrorToast(error.message),
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
            className="grid gap-3 rounded-lg border p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={ticket.status} />
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
            {ticket.assigned_to ? (
              <p className="text-xs text-muted-foreground">
                Агент: {ticket.assigned_to}
              </p>
            ) : null}
            {ticket.resolution ? (
              <div className="rounded-md border bg-muted/30 p-2 text-xs">
                <p className="font-medium">Итоговое решение</p>
                <p className="whitespace-pre-wrap">{ticket.resolution}</p>
                <p className="mt-1 text-muted-foreground">
                  Решён: {formatDateTime(ticket.resolved_at)}
                </p>
              </div>
            ) : null}

            {canResolve ? (
              <div className="flex flex-wrap gap-2">
                {ACTIVE_STATUSES.includes(ticket.status) ? (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        assignMutation.isPending ||
                        ticket.assigned_to === meQuery.data?.id
                      }
                      onClick={() => assignMutation.mutate(ticket.ticket_id)}
                    >
                      Взять себе
                    </Button>
                    <Button size="sm" onClick={() => setResolveTarget(ticket)}>
                      Ответить и решить
                    </Button>
                  </>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setReopenTarget(ticket)}
                  >
                    Переоткрыть
                  </Button>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Действия недоступны: нет права ticket:resolve.
              </p>
            )}
          </div>
        ))}
      </CardContent>

      <Dialog
        open={resolveTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setResolveTarget(null)
            setResolution("")
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ответ оператора</DialogTitle>
            <DialogDescription>
              Текст попадёт пользователю в историю обращений как шаг «human», а
              запрос выйдет из очереди.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm font-medium">{resolveTarget?.question}</p>
          <Textarea
            value={resolution}
            onChange={(event) => setResolution(event.target.value)}
            rows={5}
            placeholder="Итоговое решение для пользователя"
          />
          <DialogFooter>
            <LoadingButton
              loading={resolveMutation.isPending}
              disabled={!resolution.trim()}
              onClick={() =>
                resolveTarget && resolveMutation.mutate(resolveTarget.ticket_id)
              }
            >
              Сохранить решение
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={reopenTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setReopenTarget(null)
            setReopenReason("")
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Переоткрыть тикет</DialogTitle>
            <DialogDescription>
              Будет создан новый тикет со ссылкой на текущий, а запрос вернётся
              в очередь.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm font-medium">{reopenTarget?.question}</p>
          <Textarea
            value={reopenReason}
            onChange={(event) => setReopenReason(event.target.value)}
            rows={3}
            placeholder="Причина переоткрытия (необязательно)"
          />
          <DialogFooter>
            <LoadingButton
              loading={reopenMutation.isPending}
              onClick={() =>
                reopenTarget && reopenMutation.mutate(reopenTarget.ticket_id)
              }
            >
              Переоткрыть
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
