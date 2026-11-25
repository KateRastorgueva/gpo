import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowLeft, Send } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { UsersService } from "@/client"
import { Message } from "@/components/Support/Message"
import {
  EmptyState,
  formatDateTime,
  StatusBadge,
} from "@/components/Support/display"
import { Button } from "@/components/ui/button"
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
} from "@/services/supportApi"

const ACTIVE_STATUSES = ["open", "in_progress"]

/**
 * Страница переписки оператора с пользователем — зеркало чата поддержки:
 * слева список тикетов, справа большой чат. Входящие (пользователь и
 * автоматические ответы) слева, ответы оператора — справа.
 */
export function TicketChatPage({ ticketId }: { ticketId?: string }) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { has } = usePermissions()
  const canResolve = has(PERMISSIONS.TICKET_RESOLVE)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [reply, setReply] = useState("")
  const bottomRef = useRef<HTMLDivElement>(null)

  const ticketsQuery = useQuery({
    queryKey: ["adminTickets"],
    queryFn: getOperatorQueue,
  })
  const meQuery = useQuery({
    queryKey: ["currentUser"],
    queryFn: () => UsersService.readUserMe(),
  })

  const tickets = ticketsQuery.data?.data ?? []
  const activeTicket = ticketId
    ? (tickets.find((item) => item.ticket_id === ticketId) ?? null)
    : (tickets[0] ?? null)
  const activeId = activeTicket?.ticket_id ?? null

  const threadQuery = useQuery({
    queryKey: ["ticketThread", activeId],
    queryFn: () => getTicketThread(activeId as string),
    enabled: Boolean(activeId),
    // Пока обращение открыто — подтягиваем новые сообщения пользователя.
    refetchInterval: activeTicket && ACTIVE_STATUSES.includes(activeTicket.status)
      ? 5000
      : false,
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["adminTickets"] })
    queryClient.invalidateQueries({ queryKey: ["ticketThread", activeId] })
    queryClient.invalidateQueries({ queryKey: ["adminActiveRequests"] })
    queryClient.invalidateQueries({ queryKey: ["adminJournalRequests"] })
    queryClient.invalidateQueries({ queryKey: ["adminSupportMetrics"] })
  }

  const resolveMutation = useMutation({
    mutationFn: (text: string) => resolveTicket(activeId as string, text),
    onSuccess: () => {
      showSuccessToast("Ответ отправлен, обращение закрыто")
      setReply("")
      refresh()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const assignMutation = useMutation({
    mutationFn: () => assignTicket(activeId as string, meQuery.data?.id ?? null),
    onSuccess: () => {
      showSuccessToast("Тикет назначен на вас")
      refresh()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const reopenMutation = useMutation({
    mutationFn: () => reopenTicket(activeId as string),
    onSuccess: () => {
      showSuccessToast("Тикет переоткрыт, запрос вернулся в очередь")
      refresh()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [threadQuery.data?.steps.length, activeId])

  const closeThread = () => navigate({ to: "/admin-requests" })

  if (ticketsQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Загрузка тикетов...</p>
  }
  if (tickets.length === 0) {
    return <EmptyState text="Тикетов нет: все запросы закрыты автоматически." />
  }

  const active = activeTicket ? ACTIVE_STATUSES.includes(activeTicket.status) : false

  return (
    <div className="flex h-[calc(100vh-8rem)] min-h-[480px] overflow-hidden rounded-lg border">
      {/* Список тикетов */}
      <aside
        className={`w-full shrink-0 flex-col border-r md:flex md:w-80 ${
          activeId ? "hidden md:flex" : "flex"
        }`}
      >
        <div className="border-b p-3">
          <p className="text-sm font-semibold">Тикеты</p>
          <p className="text-xs text-muted-foreground">
            {tickets.filter((t) => ACTIVE_STATUSES.includes(t.status)).length}{" "}
            активных из {tickets.length}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {tickets.map((ticket) => (
            <Link
              key={ticket.ticket_id}
              to="/ticket/$ticketId"
              params={{ ticketId: ticket.ticket_id }}
              className={`block rounded-md px-3 py-2 ${
                ticket.ticket_id === activeId
                  ? "bg-muted"
                  : "hover:bg-muted/50"
              }`}
            >
              <div className="flex items-center gap-2">
                <StatusBadge status={ticket.status} />
                <span className="ml-auto text-xs text-muted-foreground">
                  {formatDateTime(ticket.created_at)}
                </span>
              </div>
              <p className="mt-1 truncate text-sm font-medium">
                {ticket.question}
              </p>
            </Link>
          ))}
        </div>
      </aside>

      {/* Переписка */}
      <section className="flex min-w-0 flex-1 flex-col">
        {activeTicket ? (
          <>
            <div className="flex flex-wrap items-center gap-2 border-b p-3">
              <Button
                variant="ghost"
                size="icon"
                className="md:hidden"
                onClick={closeThread}
                aria-label="К списку тикетов"
              >
                <ArrowLeft />
              </Button>
              <StatusBadge status={activeTicket.status} />
              {activeTicket.intent_label ? (
                <span className="rounded-md bg-muted px-2 py-0.5 text-xs">
                  {activeTicket.intent_label}
                </span>
              ) : null}
              <span className="text-xs text-muted-foreground">
                {activeTicket.reason}
              </span>
              <div className="ml-auto flex flex-wrap gap-2">
                {canResolve && active ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      assignMutation.isPending ||
                      activeTicket.assigned_to === meQuery.data?.id
                    }
                    onClick={() => assignMutation.mutate()}
                  >
                    Взять себе
                  </Button>
                ) : null}
                {canResolve && !active ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={reopenMutation.isPending}
                    onClick={() => reopenMutation.mutate()}
                  >
                    Переоткрыть
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4">
              {threadQuery.isPending ? (
                <p className="text-sm text-muted-foreground">
                  Загрузка переписки...
                </p>
              ) : null}
              {threadQuery.isError ? (
                <p className="text-sm text-destructive">
                  Не удалось загрузить переписку
                </p>
              ) : null}
              {threadQuery.data ? (
                <Thread thread={threadQuery.data} />
              ) : null}
              <div ref={bottomRef} />
            </div>

            {canResolve && active ? (
              <div className="border-t p-3">
                <div className="flex items-end gap-2">
                  <Textarea
                    value={reply}
                    onChange={(event) => setReply(event.target.value)}
                    rows={3}
                    placeholder="Ответ пользователю: можно вставить ссылку — она станет кликабельной"
                    aria-label="Ответ пользователю"
                    className="min-h-[72px]"
                  />
                  <LoadingButton
                    loading={resolveMutation.isPending}
                    disabled={!reply.trim()}
                    onClick={() => resolveMutation.mutate(reply.trim())}
                  >
                    <Send className="size-4" />
                    Ответить и решить
                  </LoadingButton>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Ответ появится в чате пользователя и закроет обращение.
                </p>
              </div>
            ) : null}

            {!active && activeTicket ? (
              <div className="border-t p-3 text-xs text-muted-foreground">
                Обращение закрыто
                {activeTicket.resolved_at
                  ? ` · ${formatDateTime(activeTicket.resolved_at)}`
                  : ""}
                . Чтобы ответить снова, переоткройте тикет.
              </div>
            ) : null}
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center p-6">
            <p className="text-sm text-muted-foreground">
              Выберите тикет слева
            </p>
          </div>
        )}
      </section>
    </div>
  )
}

/** Сообщения переписки: вопрос пользователя, автоответы и ответы оператора. */
function Thread({ thread }: { thread: SupportHistoryEntry }) {
  const steps = [...thread.steps].sort((a, b) => a.step_index - b.step_index)

  return (
    <div className="grid gap-3">
      {/* Входящее сообщение пользователя */}
      <Message
        type="bot"
        content={thread.question}
        createdAt={thread.created_at ?? undefined}
      />
      {steps.map((step) =>
        step.step === "human" ? (
          <Message
            key={`${step.step}-${step.step_index}`}
            type="user"
            content={step.answer}
            createdAt={step.created_at ?? undefined}
          />
        ) : (
          <Message
            key={`${step.step}-${step.step_index}`}
            type="bot"
            mode={step.step}
            content={step.answer}
            sources={step.sources}
            createdAt={step.created_at ?? undefined}
          />
        ),
      )}
      {steps.length === 0 ? (
        <p className="text-xs text-muted-foreground">Шагов обработки нет.</p>
      ) : null}
    </div>
  )
}
