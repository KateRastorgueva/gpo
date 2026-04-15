import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { type SourceAttribution } from "@/services/supportApi"

interface MessageProps {
  type: "user" | "bot"
  content: string
  mode?: string
  confidence?: number
  sources?: SourceAttribution[]
  routeReason?: string
  decisionMetrics?: {
    top_score: number
    relevant_chunks: number
    faq_score: number
    conflict: boolean
    critical: boolean
  }
  fallbackUsed?: boolean
  createdAt?: string
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

export function Message({
  type,
  content,
  mode,
  confidence,
  sources,
  routeReason,
  decisionMetrics,
  fallbackUsed,
  createdAt,
}: MessageProps) {
  if (type === "user") {
    return (
      <div className="flex justify-end mb-4">
        <Card className="max-w-[70%] bg-primary text-primary-foreground">
          <CardContent className="p-3">
            <p className="text-sm whitespace-pre-wrap">{content}</p>
            {createdAt && (
              <p className="text-xs opacity-70 mt-1">
                {new Date(createdAt).toLocaleTimeString()}
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex justify-start mb-4">
      <Card className="max-w-[70%]">
        <CardContent className="p-3">
          {mode && (
            <div className="flex items-center gap-2 mb-2">
              <Badge variant={modeBadgeVariant(mode)}>{mode}</Badge>
              <span className="text-xs text-muted-foreground">
                {modeLabel(mode)}
              </span>
            </div>
          )}
          <p className="text-sm whitespace-pre-wrap mb-2">{content}</p>
          {routeReason && (
            <p className="text-xs text-muted-foreground mb-1">
              Причина маршрута: {routeReasonLabel(routeReason)}
            </p>
          )}
          {confidence !== undefined && (
            <p className="text-xs text-muted-foreground mb-1">
              confidence: {confidence.toFixed(2)} | fallback:{" "}
              {fallbackUsed ? "ollama" : "google"}
            </p>
          )}
          {decisionMetrics && (
            <p className="text-xs text-muted-foreground mb-2">
              decision: top_score={decisionMetrics.top_score.toFixed(2)}, relevant_chunks=
              {decisionMetrics.relevant_chunks}, faq_score=
              {decisionMetrics.faq_score.toFixed(2)}, conflict=
              {String(decisionMetrics.conflict)}, critical=
              {String(decisionMetrics.critical)}
            </p>
          )}
          {sources && sources.length > 0 && <SourceList sources={sources} />}
          {createdAt && (
            <p className="text-xs text-muted-foreground mt-2">
              {new Date(createdAt).toLocaleTimeString()}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function SourceList({ sources }: { sources: SourceAttribution[] }) {
  return (
    <div className="grid gap-2 mt-2">
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