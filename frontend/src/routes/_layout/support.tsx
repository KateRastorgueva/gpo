import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"

import { LoadingButton } from "@/components/ui/loading-button"
import { StepsTimeline } from "@/components/Support/display"
import { FeedbackForm } from "@/components/Support/FeedbackForm"
import { Message } from "@/components/Support/Message"
import useCustomToast from "@/hooks/useCustomToast"
import {
  askSupport,
  getSupportHistory,
} from "@/services/supportApi"

type Chat = {
  sessionId: string
  title: string
  lastMessageAt: string
  messageCount: number
}

const STORAGE_KEY = "support_chats"

const getChats = (): Chat[] => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

const saveChats = (chats: Chat[]) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(chats))
}

const createNewChat = (): Chat => {
  const sessionId = crypto.randomUUID()
  const chat: Chat = {
    sessionId,
    title: "Новый чат",
    lastMessageAt: new Date().toISOString(),
    messageCount: 0,
  }
  const chats = getChats()
  chats.unshift(chat)
  saveChats(chats)
  return chat
}

const updateChat = (sessionId: string, updates: Partial<Chat>) => {
  const chats = getChats()
  const index = chats.findIndex(c => c.sessionId === sessionId)
  if (index !== -1) {
    chats[index] = { ...chats[index], ...updates }
    saveChats(chats)
  }
}

export const Route = createFileRoute("/_layout/support")({
  component: SupportPage,
  head: () => ({
    meta: [{ title: "Support - FastAPI Template" }],
  }),
})

function SupportPage() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [chats, setChats] = useState<Chat[]>(() => getChats())
  const [selectedChat, setSelectedChat] = useState<Chat | null>(null)
  const [question, setQuestion] = useState("")
  const queryClient = useQueryClient()
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const historyQuery = useQuery({
    queryKey: ["supportHistory", selectedChat?.sessionId],
    queryFn: () => selectedChat ? getSupportHistory(selectedChat.sessionId) : Promise.resolve({ data: [], count: 0 }),
    enabled: !!selectedChat,
  })

  const askMutation = useMutation({
    mutationFn: () => askSupport({ question, session_id: selectedChat!.sessionId, channel: "web" }),
    onSuccess: () => {
      setQuestion("")
      showSuccessToast("Ответ получен")
      queryClient.invalidateQueries({ queryKey: ["supportHistory", selectedChat!.sessionId] })
      // Update chat title and metadata
      const history = historyQuery.data?.data || []
      const firstQuestion = history.length === 0 ? question : history[0].question
      updateChat(selectedChat!.sessionId, {
        title: firstQuestion.length > 50 ? firstQuestion.substring(0, 50) + "..." : firstQuestion,
        lastMessageAt: new Date().toISOString(),
        messageCount: history.length + 2, // question + answer
      })
      setChats(getChats())
    },
    onError: (error: Error) => {
      showErrorToast(error.message)
    },
  })

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [historyQuery.data])

  const submitQuestion = () => {
    if (!question.trim() || !selectedChat) {
      showErrorToast("Введите вопрос")
      return
    }
    if (askMutation.isPending) return
    askMutation.mutate()
  }

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      submitQuestion()
    }
  }

  const handleNewChat = () => {
    const newChat = createNewChat()
    setChats(getChats())
    setSelectedChat(newChat)
  }

  const handleSelectChat = (chat: Chat) => {
    setSelectedChat(chat)
  }

  const handleBackToList = () => {
    setSelectedChat(null)
  }

  if (selectedChat) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-4 p-4 border-b">
          <button
            onClick={handleBackToList}
            className="text-muted-foreground hover:text-foreground"
          >
            ← Назад к чатам
          </button>
          <h2 className="font-semibold truncate">{selectedChat.title}</h2>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {historyQuery.isPending ? (
            <p className="text-sm text-muted-foreground text-center">Загрузка истории...</p>
          ) : historyQuery.data?.data.length ? (
            historyQuery.data.data.map((entry) => (
              <div key={entry.request_id}>
                <Message
                  type="user"
                  content={entry.question}
                  createdAt={entry.created_at || undefined}
                />
                <Message
                  type="bot"
                  content={entry.answer}
                  mode={entry.mode}
                  confidence={entry.confidence}
                  sources={entry.sources}
                  fallbackUsed={entry.fallback_used}
                />
                {entry.steps.length > 1 ? (
                  <StepsTimeline steps={entry.steps} />
                ) : null}
                <FeedbackForm requestId={entry.request_id} />
              </div>
            ))
          ) : (
            <div className="text-center text-muted-foreground">
              <p>Начните разговор с техподдержкой!</p>
              <p>Задайте свой первый вопрос ниже.</p>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        <div className="border-t p-4">
          <div className="flex gap-2">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyPress={handleKeyPress}
              rows={2}
              placeholder="Опишите ваш вопрос..."
              className="flex-1 rounded-md border bg-background p-3 text-sm resize-none"
              disabled={askMutation.isPending}
            />
            <LoadingButton
              loading={askMutation.isPending}
              onClick={submitQuestion}
              className="self-end"
            >
              Отправить
            </LoadingButton>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            Ответ будет сформирован по FAQ/документам или передан оператору.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b">
        <h1 className="text-2xl font-bold">Техподдержка</h1>
        <button
          onClick={handleNewChat}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
        >
          Новый чат
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {chats.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center p-8">
            <p className="text-muted-foreground mb-4">У вас пока нет активных чатов</p>
            <button
              onClick={handleNewChat}
              className="px-6 py-3 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
            >
              Начать новый чат
            </button>
          </div>
        ) : (
          <div className="p-4 space-y-2">
            {chats.map((chat) => (
              <div
                key={chat.sessionId}
                onClick={() => handleSelectChat(chat)}
                className="p-4 border rounded-lg cursor-pointer hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <h3 className="font-medium truncate">{chat.title}</h3>
                  <span className="text-xs text-muted-foreground">
                    {new Date(chat.lastMessageAt).toLocaleDateString()}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  {chat.messageCount} сообщений
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


