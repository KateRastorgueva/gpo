import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  askSupport,
  getSupportHistory,
  type SourceAttribution,
  type SupportAskResponse,
} from "@/services/supportApi"

const getOrCreateSessionId = () => {
  const key = "support_session_id"
  const existing = localStorage.getItem(key)
  if (existing) return existing
  const next = crypto.randomUUID()
  localStorage.setItem(key, next)
  return next
}

const modeBadgeVariant = (mode: string) => {
  if (mode === "faq") return "default"
  if (mode === "rag") return "secondary"
  return "destructive"
}

const modeLabel = (mode: string) => {
  if (mode === "faq") return "FAQ template"
  if (mode === "rag") return "RAG from sources"
  return "Operator escalation"
}

const routeReasonLabel = (reason: string) => {
  const labels: Record<string, string> = {
    faq_hit: "Найдено совпадение в FAQ",
    rag_answer: "Ответ сформирован по источникам",
    insufficient_context: "Недостаточно контекста в базе знаний",
    conflict: "Конфликт релевантных источников",
    retrieval_failure: "Поиск по знаниям недоступен",
    critical_low_confidence: "Критичный вопрос при низкой уверенности",
    llm_failure: "Ошибка генерации ответа",
    empty_answer: "Пустой ответ модели",
  }
  return labels[reason] || reason
}

export const Route = createFileRoute("/_layout/support")({
  component: SupportPage,
  head: () => ({
    meta: [{ title: "Support - FastAPI Template" }],
  }),
})

function SupportPage() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [question, setQuestion] = useState("")
  const [latestResponse, setLatestResponse] = useState<SupportAskResponse | null>(
    null,
  )
  const [sessionId] = useState(getOrCreateSessionId)
  const queryClient = useQueryClient()

  const historyQuery = useQuery({
    queryKey: ["supportHistory", sessionId],
    queryFn: () => getSupportHistory(sessionId),
  })

  const askMutation = useMutation({
    mutationFn: () => askSupport({ question, session_id: sessionId, channel: "web" }),
    onSuccess: (response) => {
      setLatestResponse(response)
      setQuestion("")
      showSuccessToast("Ответ получен")
      queryClient.invalidateQueries({ queryKey: ["supportHistory", sessionId] })
    },
    onError: (error: Error) => {
      showErrorToast(error.message)
    },
  })

  const submitQuestion = () => {
    if (!question.trim()) {
      showErrorToast("Введите вопрос")
      return
    }
    if (askMutation.isPending) return
    askMutation.mutate()
  }

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Техподдержка университета</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={4}
            placeholder="Опишите ваш вопрос"
            className="w-full rounded-md border bg-background p-3 text-sm"
          />
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              Ответ будет сформирован по FAQ/документам или передан оператору.
            </p>
            <LoadingButton loading={askMutation.isPending} onClick={submitQuestion}>
              Отправить
            </LoadingButton>
          </div>
        </CardContent>
      </Card>

      {latestResponse && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-lg">Последний ответ</CardTitle>
            <Badge variant={modeBadgeVariant(latestResponse.mode)}>
              {latestResponse.mode}
            </Badge>
          </CardHeader>
          <CardContent className="grid gap-3">
            <p className="text-xs text-muted-foreground">
              Answer type: {modeLabel(latestResponse.mode)}
            </p>
            <p className="text-xs text-muted-foreground">
              Причина маршрута: {routeReasonLabel(latestResponse.route_reason)}
            </p>
            <p className="text-sm whitespace-pre-wrap">{latestResponse.answer}</p>
            <p className="text-xs text-muted-foreground">
              confidence: {latestResponse.confidence.toFixed(2)} | fallback:{" "}
              {latestResponse.fallback_used ? "ollama" : "google"}
            </p>
            <p className="text-xs text-muted-foreground">
              decision: top_score=
              {latestResponse.decision_metrics.top_score.toFixed(2)}, relevant_chunks=
              {latestResponse.decision_metrics.relevant_chunks}, faq_score=
              {latestResponse.decision_metrics.faq_score.toFixed(2)}, conflict=
              {String(latestResponse.decision_metrics.conflict)}, critical=
              {String(latestResponse.decision_metrics.critical)}
            </p>
            <SourceList sources={latestResponse.sources} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">История сессии</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          {historyQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка истории...</p>
          ) : null}
          {historyQuery.data?.data.length ? (
            historyQuery.data.data.map((entry) => (
              <div key={entry.request_id} className="rounded-md border p-3">
                <div className="mb-2 flex items-center gap-2">
                  <Badge variant={modeBadgeVariant(entry.mode)}>{entry.mode}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {modeLabel(entry.mode)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {entry.created_at
                      ? new Date(entry.created_at).toLocaleString()
                      : ""}
                  </span>
                </div>
                <p className="text-sm font-medium">{entry.question}</p>
                <p className="mt-1 text-sm whitespace-pre-wrap">{entry.answer}</p>
                <SourceList sources={entry.sources} />
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">История пока пустая.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function SourceList({ sources }: { sources: SourceAttribution[] }) {
  if (!sources.length) return null
  return (
    <div className="grid gap-2">
      <p className="text-xs font-medium uppercase text-muted-foreground">Источники</p>
      {sources.map((source) => (
        <div key={`${source.source_id}-${source.chunk_id || "none"}`} className="rounded border p-2 text-xs">
          <p className="font-medium">{source.source_title}</p>
          {source.source_ref ? (
            <a
              className="text-primary underline break-all"
              href={source.source_ref}
              target="_blank"
              rel="noreferrer"
            >
              {source.source_ref}
            </a>
          ) : null}
          {source.snippet ? (
            <p className="mt-1 text-muted-foreground">{source.snippet}</p>
          ) : null}
        </div>
      ))}
    </div>
  )
}
