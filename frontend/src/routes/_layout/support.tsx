import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Send, Sparkles } from "lucide-react"
import { useState } from "react"
import {
  EmptyState,
  ModeBadge,
  modeLabel,
  routeReasonLabel,
  SourceList,
  StepsTimeline,
} from "@/components/Support/display"
import { FeedbackForm } from "@/components/Support/FeedbackForm"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { LoadingButton } from "@/components/ui/loading-button"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import {
  askSupport,
  getSupportHistory,
  type SupportAskResponse,
  type SupportHistoryEntry,
} from "@/services/supportApi"

const getOrCreateSessionId = () => {
  const key = "support_session_id"
  const existing = localStorage.getItem(key)
  if (existing) return existing
  const next = crypto.randomUUID()
  localStorage.setItem(key, next)
  return next
}

export const Route = createFileRoute("/_layout/support")({
  component: SupportPage,
  head: () => ({
    meta: [{ title: "Техподдержка" }],
  }),
})

function SupportPage() {
  const { showErrorToast } = useCustomToast()
  const [question, setQuestion] = useState("")
  const [latestResponse, setLatestResponse] =
    useState<SupportAskResponse | null>(null)
  const [rated, setRated] = useState<Record<string, number>>({})
  const [sessionId] = useState(getOrCreateSessionId)
  const queryClient = useQueryClient()

  const historyQuery = useQuery({
    queryKey: ["supportHistory", sessionId],
    queryFn: () => getSupportHistory(sessionId),
  })

  const askMutation = useMutation({
    mutationFn: () =>
      askSupport({
        question: question.trim(),
        session_id: sessionId,
        channel: "web",
      }),
    onSuccess: (response) => {
      setLatestResponse(response)
      setQuestion("")
      queryClient.invalidateQueries({ queryKey: ["supportHistory", sessionId] })
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const submitQuestion = () => {
    if (!question.trim()) {
      showErrorToast("Введите вопрос")
      return
    }
    if (askMutation.isPending) return
    askMutation.mutate()
  }

  const history = historyQuery.data?.data ?? []

  return (
    <div className="mx-auto grid w-full max-w-3xl gap-6">
      <div>
        <h1 className="text-2xl font-semibold">Техподдержка университета</h1>
        <p className="text-sm text-muted-foreground">
          Ответ формируется по базе знаний, а если оснований недостаточно —
          вопрос уходит оператору.
        </p>
      </div>

      <Card>
        <CardContent className="grid gap-3 pt-6">
          <Textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                submitQuestion()
              }
            }}
            rows={4}
            placeholder="Опишите ваш вопрос (Ctrl+Enter — отправить)"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              Отвечаем по базе знаний; при нехватке данных подключается
              оператор.
            </p>
            <LoadingButton
              loading={askMutation.isPending}
              onClick={submitQuestion}
            >
              <Send className="size-4" />
              Отправить
            </LoadingButton>
          </div>
        </CardContent>
      </Card>

      {latestResponse ? (
        <Card>
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-lg">Ответ</CardTitle>
            <div className="flex items-center gap-2">
              <ModeBadge mode={latestResponse.mode} />
              <Badge variant="outline">
                уверенность {latestResponse.confidence.toFixed(2)}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4">
            {latestResponse.escalated ? (
              <Alert>
                <Sparkles className="size-4" />
                <AlertTitle>Вопрос передан оператору</AlertTitle>
                <AlertDescription>
                  Автоматический ответ недостаточно надёжен. Оператор ответит, и
                  ответ появится в истории ниже.
                </AlertDescription>
              </Alert>
            ) : null}
            <p className="text-sm whitespace-pre-wrap">
              {latestResponse.answer}
            </p>
            <dl className="grid gap-1 text-xs text-muted-foreground">
              <div className="flex gap-2">
                <dt>Тип ответа:</dt>
                <dd>{modeLabel(latestResponse.mode)}</dd>
              </div>
              <div className="flex gap-2">
                <dt>Причина маршрута:</dt>
                <dd>{routeReasonLabel(latestResponse.route_reason)}</dd>
              </div>
              <div className="flex gap-2">
                <dt>Генерация:</dt>
                <dd>
                  {latestResponse.fallback_used
                    ? "Ollama (fallback)"
                    : "Google AI"}
                </dd>
              </div>
            </dl>
            <SourceList sources={latestResponse.sources} />
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Метрики решения</summary>
              <pre className="mt-2 overflow-x-auto rounded border bg-muted/30 p-2">
                {JSON.stringify(latestResponse.decision_metrics, null, 2)}
              </pre>
            </details>
            <FeedbackForm
              requestId={latestResponse.request_id}
              onSubmitted={(requestId, rating) =>
                setRated((current) => ({ ...current, [requestId]: rating }))
              }
            />
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">История обращений</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {historyQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка истории...</p>
          ) : null}
          {!historyQuery.isPending && history.length === 0 ? (
            <EmptyState text="Обращений пока нет — задайте первый вопрос." />
          ) : null}
          {history.map((entry) => (
            <HistoryCard
              key={entry.request_id}
              entry={entry}
              rated={rated[entry.request_id]}
              onSubmitted={(requestId, rating) =>
                setRated((current) => ({ ...current, [requestId]: rating }))
              }
            />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

function HistoryCard({
  entry,
  rated,
  onSubmitted,
}: {
  entry: SupportHistoryEntry
  rated?: number
  onSubmitted: (requestId: string, rating: number) => void
}) {
  // Для пользователя шаги показываем только когда ответ давал не только автомат
  const showSteps = entry.steps.length > 1
  const awaitingOperator = entry.steps.some((step) => !step.is_final)

  return (
    <div className="grid gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <ModeBadge mode={entry.mode} />
        <Badge variant="outline">
          уверенность {entry.confidence.toFixed(2)}
        </Badge>
        {awaitingOperator ? (
          <Badge variant="destructive">ждёт оператора</Badge>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {entry.created_at ? new Date(entry.created_at).toLocaleString() : ""}
        </span>
      </div>
      <div>
        <p className="text-xs font-medium uppercase text-muted-foreground">
          Вопрос
        </p>
        <p className="text-sm font-medium">{entry.question}</p>
      </div>
      <div>
        <p className="text-xs font-medium uppercase text-muted-foreground">
          Ответ
        </p>
        <p className="text-sm whitespace-pre-wrap">{entry.answer}</p>
      </div>
      <SourceList sources={entry.sources} />
      {showSteps ? <StepsTimeline steps={entry.steps} /> : null}
      {rated ? (
        <p className="text-xs text-muted-foreground">
          Ваша оценка: {rated} из 5
        </p>
      ) : (
        <FeedbackForm requestId={entry.request_id} onSubmitted={onSubmitted} />
      )}
    </div>
  )
}
