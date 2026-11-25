import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { UsersService } from "@/client"
import { Message } from "@/components/Support/Message"
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
  getTicketThread,
  reopenTicket,
  resolveTicket,
  type SupportHistoryEntry,
  type SupportTicket,
} from "@/services/supportApi"

const ACTIVE_STATUSES = ["open", "in_progress"]

/** Переписка по тикету: вопрос, автоответ с источниками и ответы оператора. */
function TicketThread({
  ticket,
  canResolve,
  onResolved,
}: {
  ticket: SupportTicket
  canResolve: boolean
  onResolved: () => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [reply, setReply] = useState("")
  const threadQuery = useQuery({
    queryKey: ["ticketThread", ticket.ticket_id],
    queryFn: () => getTicketThread(ticket.ticket_id),
  })

  const resolveMutation = useMutation({
    mutationFn: (text: string) => resolveTicket(ticket.ticket_id, text),
    onSuccess: () => {
      showSuccessToast("Ответ оператора сохранён, запрос закрыт")
      setReply("")
      queryClient.invalidateQueries({
        queryKey: ["ticketThread", ticket.ticket_id],
      })
      onResolved()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const thread = threadQuery.data
  const active = ACTIVE_STATUSES.includes(ticket.status)

  return (
    <div className="grid gap-3 rounded-lg border bg-muted/20 p-3">
      {threadQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Загрузка переписки...</p>
      ) : null}
      {threadQuery.isError ? (
        <p className="text-sm text-destructive">
          Не удалось загрузить переписку
        </p>
      ) : null}

      {thread ? <ThreadMessages thread={thread} /> : null}

      {canResolve && active ? (
        <div className="grid gap-2">
          <Textarea
            value={reply}
            onChange={(event) => setReply(event.target.value)}
            rows={3}
            placeholder="Ответ пользователю: можно вставить ссылку — она станет кликабельной"
            aria-label="Ответ пользователю"
          />
          <div className="flex items-center gap-2">
            <LoadingButton
              loading={resolveMutation.isPending}
              disabled={!reply.trim()}
              onClick={() => resolveMutation.mutate(reply.trim())}
            >
              Ответить и решить
            </LoadingButton>
            <span className="text-xs text-muted-foreground">
              Ответ появится в чате пользователя и закроет обращение.
            </span>
          </div>
        </div>
      ) : null}

      {!active && ticket.resolution ? (
        <div className="rounded-md border bg-background p-2 text-xs">
          <p className="font-medium">Итоговое решение</p>
          <p className="whitespace-pre-wrap">{ticket.resolution}</p>
          <p className="mt-1 text-muted-foreground">
            Решён: {formatDateTime(ticket.resolved_at)}
          </p>
        </div>
      ) : null}
    </div>
  )
}

/** Сообщения переписки: вопрос пользователя и все шаги обработки. */
function ThreadMessages({ thread }: { thread: SupportHistoryEntry }) {
  const steps = [...thread.steps].sort((a, b) => a.step_index - b.step_index)

  return (
    <div className="grid gap-2">
      <Message
        type="user"
        content={thread.question}
        createdAt={thread.created_at ?? undefined}
      />
      {steps.map((step) => (
        <Message
          key={`${step.step}-${step.step_index}`}
          type="bot"
          mode={step.step}
          content={step.answer}
          sources={step.sources}
          createdAt={step.created_at ?? undefined}
        />
      ))}
      {steps.length === 0 ? (
        <p className="text-xs text-muted-foreground">Шагов обработки нет.</p>
      ) : null}
    </div>
  )
}

export function TicketsPanel() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { has } = usePermissions()
  // Без ticket:resolve тикеты доступны только на чтение
  const canResolve = has(PERMISSIONS.TICKET_RESOLVE)
  const queryClient = useQueryClient()
  const [openThread, setOpenThread] = useState<string | null>(null)
  const [reopenTarget, setReopenTarget] = useState<SupportTicket | null>(null)
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

        {tickets.map((ticket) => {
          const expanded = openThread === ticket.ticket_id
          return (
            <div
              key={ticket.ticket_id}
              data-testid="ticket-card"
              className="grid gap-3 rounded-lg border p-4"
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

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={expanded ? "default" : "outline"}
                  onClick={() =>
                    setOpenThread(expanded ? null : ticket.ticket_id)
                  }
                >
                  {expanded ? "Скрыть переписку" : "Переписка"}
                </Button>
                {canResolve && ACTIVE_STATUSES.includes(ticket.status) ? (
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
                ) : null}
                {canResolve && !ACTIVE_STATUSES.includes(ticket.status) ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setReopenTarget(ticket)}
                  >
                    Переоткрыть
                  </Button>
                ) : null}
                {!canResolve ? (
                  <span className="self-center text-xs text-muted-foreground">
                    Действия недоступны: нет права ticket:resolve.
                  </span>
                ) : null}
              </div>

              {expanded ? (
                <TicketThread
                  ticket={ticket}
                  canResolve={canResolve}
                  onResolved={refresh}
                />
              ) : null}
            </div>
          )
        })}
      </CardContent>

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
