import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ArrowLeft, Loader2, Plus, Send, Trash2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { FeedbackForm } from "@/components/Support/FeedbackForm"
import { Message } from "@/components/Support/Message"
import { Button } from "@/components/ui/button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  askSupport,
  getSupportHistory,
  type SupportHistoryEntry,
} from "@/services/supportApi"

type Chat = {
  sessionId: string
  title: string
  lastMessageAt: string
}

const STORAGE_KEY = "support_chats"

const EXAMPLE_PROMPTS = [
  "Где смотреть расписание занятий ТУСУР?",
  "Как восстановиться после отчисления?",
  "Как оформить академический отпуск?",
  "Сколько длится академическая пара?",
]

const loadChats = (): Chat[] => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

const storeChats = (chats: Chat[]) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(chats))
  } catch {
    // localStorage недоступен (приватный режим) — чаты живут до перезагрузки
  }
}

// Удалённые из списка чаты: на сервере история остаётся (её видит оператор),
// поэтому прячем их по session_id.
const HIDDEN_KEY = "support_hidden_chats"

const loadHidden = (): string[] => {
  try {
    return JSON.parse(localStorage.getItem(HIDDEN_KEY) ?? "[]")
  } catch {
    return []
  }
}

const hideChat = (sessionId: string) => {
  try {
    localStorage.setItem(
      HIDDEN_KEY,
      JSON.stringify([...new Set([...loadHidden(), sessionId])]),
    )
  } catch {
    // без localStorage чат вернётся после перезагрузки
  }
}

const shortTitle = (text: string) =>
  text.length > 60 ? `${text.slice(0, 60)}…` : text

// Чаты с сервера: обращения пользователя, сгруппированные по session_id.
// Так история видна в любом браузере, а не только там, где чат начинали.
const chatsFromHistory = (entries: SupportHistoryEntry[]): Chat[] => {
  const bySession = new Map<string, Chat>()
  // История приходит от новых к старым: первое попадание — последнее сообщение.
  for (const entry of entries) {
    if (!entry.session_id) continue
    const existing = bySession.get(entry.session_id)
    if (!existing) {
      bySession.set(entry.session_id, {
        sessionId: entry.session_id,
        title: shortTitle(entry.question),
        lastMessageAt: entry.created_at ?? new Date().toISOString(),
      })
    } else {
      existing.title = shortTitle(entry.question)
    }
  }
  return [...bySession.values()]
}

// Автоответ системы = первый не-операторский шаг; ответ оператора идёт отдельно.
const autoAnswer = (entry: SupportHistoryEntry) =>
  entry.steps.find((step) => step.step !== "human")?.answer ?? entry.answer

// Ответ оператора приходит отдельным финальным шагом "human".
const operatorReply = (entry: SupportHistoryEntry) =>
  entry.steps.find((step) => step.step === "human" && step.is_final)

const waitsForOperator = (entry: SupportHistoryEntry) =>
  entry.escalated && !operatorReply(entry)

export const Route = createFileRoute("/_layout/support")({
  component: SupportPage,
  head: () => ({
    meta: [{ title: "Техподдержка ТУСУР" }],
  }),
})

function SupportPage() {
  const { showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [chats, setChats] = useState<Chat[]>(loadChats)
  const [activeId, setActiveId] = useState<string | null>(
    () => loadChats()[0]?.sessionId ?? null,
  )
  const [draft, setDraft] = useState("")
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const updateChats = (next: Chat[]) => {
    setChats(next)
    storeChats(next)
  }

  const serverChatsQuery = useQuery({
    queryKey: ["supportChats"],
    queryFn: () => getSupportHistory(undefined, 200),
  })

  // Склеиваем локальные чаты (в т.ч. только что созданные, пустые) с серверными.
  useEffect(() => {
    const hidden = new Set(loadHidden())
    const fromServer = chatsFromHistory(
      serverChatsQuery.data?.data ?? [],
    ).filter((chat) => !hidden.has(chat.sessionId))
    if (!fromServer.length) return
    setChats((local) => {
      const merged = new Map(local.map((chat) => [chat.sessionId, chat]))
      for (const chat of fromServer) {
        const current = merged.get(chat.sessionId)
        merged.set(chat.sessionId, {
          ...chat,
          lastMessageAt:
            current && current.lastMessageAt > chat.lastMessageAt
              ? current.lastMessageAt
              : chat.lastMessageAt,
        })
      }
      const next = [...merged.values()].sort((a, b) =>
        b.lastMessageAt.localeCompare(a.lastMessageAt),
      )
      storeChats(next)
      return next
    })
    setActiveId((id) => id ?? fromServer[0]?.sessionId ?? null)
  }, [serverChatsQuery.data])

  const activeChat = chats.find((chat) => chat.sessionId === activeId) ?? null

  const historyQuery = useQuery({
    queryKey: ["supportHistory", activeId],
    queryFn: () => getSupportHistory(activeId as string),
    enabled: !!activeId,
    // Опрос нужен только пока обращение ждёт ответа оператора.
    refetchInterval: (query) =>
      query.state.data?.data.some(waitsForOperator) ? 5000 : false,
  })

  // API отдаёт историю от новых к старым, в чате нужен обратный порядок.
  const entries = useMemo(
    () => [...(historyQuery.data?.data ?? [])].reverse(),
    [historyQuery.data],
  )

  const askMutation = useMutation({
    mutationFn: (vars: { question: string; sessionId: string }) =>
      askSupport({
        question: vars.question,
        session_id: vars.sessionId,
        channel: "web",
      }),
    onSettled: async (_data, _error, vars) => {
      await queryClient.invalidateQueries({
        queryKey: ["supportHistory", vars.sessionId],
      })
      queryClient.invalidateQueries({ queryKey: ["supportChats"] })
      setPendingQuestion(null)
    },
    onError: (error: Error, vars) => {
      setDraft(vars.question)
      showErrorToast(error.message)
    },
  })

  // Прокрутка к последнему сообщению при новых ответах и при отправке вопроса.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [entries.length, pendingQuestion, activeId])

  useEffect(() => {
    inputRef.current?.focus()
  }, [activeId])

  const startChat = (title = "Новый чат") => {
    const chat: Chat = {
      sessionId: crypto.randomUUID(),
      title,
      lastMessageAt: new Date().toISOString(),
    }
    updateChats([chat, ...chats])
    setActiveId(chat.sessionId)
    return chat
  }

  const send = (text?: string) => {
    const question = (text ?? draft).trim()
    if (!question || askMutation.isPending) return
    const chat = activeChat ?? startChat(shortTitle(question))
    const isFirst = !activeChat || entries.length === 0
    updateChats(
      [chat, ...chats.filter((c) => c.sessionId !== chat.sessionId)].map((c) =>
        c.sessionId === chat.sessionId
          ? {
              ...c,
              title: isFirst ? shortTitle(question) : c.title,
              lastMessageAt: new Date().toISOString(),
            }
          : c,
      ),
    )
    setDraft("")
    setPendingQuestion(question)
    askMutation.mutate({ question, sessionId: chat.sessionId })
  }

  const deleteChat = (sessionId: string) => {
    const next = chats.filter((chat) => chat.sessionId !== sessionId)
    hideChat(sessionId)
    updateChats(next)
    queryClient.removeQueries({ queryKey: ["supportHistory", sessionId] })
    if (activeId === sessionId) setActiveId(next[0]?.sessionId ?? null)
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }

  const isEmpty = !historyQuery.isFetching && entries.length === 0

  return (
    <div className="flex h-[calc(100vh-8rem)] min-h-[480px] overflow-hidden rounded-lg border">
      {/* Список чатов: на телефоне виден, только когда чат не открыт */}
      <aside
        className={`w-full shrink-0 flex-col border-r md:flex md:w-72 ${
          activeId ? "hidden" : "flex"
        }`}
      >
        <div className="flex items-center justify-between gap-2 border-b p-3">
          <h1 className="text-lg font-semibold">Техподдержка</h1>
          <Button size="sm" onClick={() => startChat()}>
            <Plus />
            Новый
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {chats.length === 0 ? (
            <p className="p-4 text-center text-sm text-muted-foreground">
              Чатов пока нет
            </p>
          ) : (
            chats.map((chat) => (
              <div
                key={chat.sessionId}
                className={`group flex items-center rounded-md ${
                  chat.sessionId === activeId ? "bg-muted" : "hover:bg-muted/50"
                }`}
              >
                <button
                  type="button"
                  onClick={() => setActiveId(chat.sessionId)}
                  className="min-w-0 flex-1 px-3 py-2 text-left"
                >
                  <p className="truncate text-sm font-medium">{chat.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {new Date(chat.lastMessageAt).toLocaleString()}
                  </p>
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="mr-1 opacity-60 hover:opacity-100"
                  onClick={() => deleteChat(chat.sessionId)}
                  aria-label="Удалить чат"
                  title="Удалить чат"
                >
                  <Trash2 />
                </Button>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Окно переписки */}
      <section
        className={`min-w-0 flex-1 flex-col ${activeId ? "flex" : "hidden md:flex"}`}
      >
        <div className="flex items-center gap-2 border-b p-3">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setActiveId(null)}
            aria-label="К списку чатов"
          >
            <ArrowLeft />
          </Button>
          <h2 className="truncate font-medium">
            {activeChat?.title ?? "Новый чат"}
          </h2>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          <div className="mx-auto flex max-w-3xl flex-col gap-3">
            {activeId && historyQuery.isPending ? (
              <p className="text-center text-sm text-muted-foreground">
                Загрузка истории…
              </p>
            ) : null}

            {isEmpty && !pendingQuestion ? (
              <div className="grid gap-4 py-10 text-center">
                <div>
                  <p className="text-lg font-medium">Чем помочь?</p>
                  <p className="text-sm text-muted-foreground">
                    Ответ найдём в FAQ и документах университета, а если не
                    получится, передадим вопрос оператору.
                  </p>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {EXAMPLE_PROMPTS.map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => send(example)}
                      className="rounded-md border p-3 text-left text-sm hover:bg-muted/50"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {entries.map((entry) => {
              const reply = operatorReply(entry)
              return (
                <div key={entry.request_id} className="flex flex-col gap-3">
                  <Message
                    type="user"
                    content={entry.question}
                    createdAt={entry.created_at || undefined}
                  />
                  <Message
                    type="bot"
                    content={autoAnswer(entry)}
                    mode={entry.mode}
                    confidence={entry.confidence}
                    sources={entry.sources}
                    createdAt={entry.created_at || undefined}
                  />
                  {reply ? (
                    <Message
                      type="bot"
                      mode="human"
                      content={reply.answer}
                      createdAt={reply.created_at || undefined}
                    />
                  ) : null}
                  {waitsForOperator(entry) ? (
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="size-3 animate-spin" />
                      Оператор ещё не ответил, ответ появится здесь
                      автоматически
                    </p>
                  ) : null}
                  {!entry.escalated || reply ? (
                    <details className="ml-2 text-xs text-muted-foreground">
                      <summary className="cursor-pointer">Оценить ответ</summary>
                      <div className="mt-2 max-w-md">
                        <FeedbackForm requestId={entry.request_id} />
                      </div>
                    </details>
                  ) : null}
                </div>
              )
            })}

            {pendingQuestion ? (
              <div className="flex flex-col gap-3">
                <Message type="user" content={pendingQuestion} />
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Ищу ответ в документах, это может занять до минуты…
                </div>
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t p-3">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              rows={2}
              placeholder="Опишите ваш вопрос… (Enter — отправить, Shift+Enter — новая строка)"
              className="max-h-40 min-h-[44px] flex-1 resize-none rounded-md border bg-background p-3 text-sm"
              disabled={askMutation.isPending}
            />
            <Button
              onClick={() => send()}
              disabled={askMutation.isPending || !draft.trim()}
              aria-label="Отправить"
            >
              {askMutation.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Send />
              )}
            </Button>
          </div>
        </div>
      </section>
    </div>
  )
}
