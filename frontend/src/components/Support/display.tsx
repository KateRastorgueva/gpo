import { Badge } from "@/components/ui/badge"
import type {
  SourceAttribution,
  SupportStep,
  SupportStepKind,
} from "@/services/supportApi"

type BadgeVariant = "default" | "secondary" | "destructive" | "outline"

const MODE_LABELS: Record<string, string> = {
  faq: "Шаблон FAQ",
  rag: "Ответ по базе знаний",
  operator: "Передан оператору",
  human: "Ответ оператора",
}

const ROUTE_REASON_LABELS: Record<string, string> = {
  faq_hit: "Найдено совпадение в базе знаний",
  rag_answer: "Ответ сформирован по источникам",
  insufficient_context: "Недостаточно контекста в базе знаний",
  conflict: "Конфликт релевантных источников",
  retrieval_failure: "Поиск по знаниям недоступен",
  critical_low_confidence: "Критичный вопрос при низкой уверенности",
  llm_failure: "Ошибка генерации ответа",
  empty_answer: "Пустой ответ модели",
}

const STATUS_LABELS: Record<string, string> = {
  open: "Открыт",
  in_progress: "В работе",
  resolved: "Решён",
  closed: "Закрыт",
  queued: "В очереди",
  answered: "Отвечен",
  pending: "Ожидает индексации",
  indexed: "Проиндексирован",
  failed: "Ошибка",
  deleted: "Удалён",
}

export const modeVariant = (mode: string): BadgeVariant => {
  if (mode === "faq") return "default"
  if (mode === "rag") return "secondary"
  if (mode === "human") return "outline"
  return "destructive"
}

export const modeLabel = (mode: string) => MODE_LABELS[mode] || mode

export const routeReasonLabel = (reason: string) =>
  ROUTE_REASON_LABELS[reason] || reason

export const statusLabel = (status: string) => STATUS_LABELS[status] || status

export const statusVariant = (status: string): BadgeVariant => {
  if (["open", "queued", "failed", "deleted"].includes(status)) {
    return "destructive"
  }
  if (["in_progress"].includes(status)) return "default"
  if (["pending"].includes(status)) return "outline"
  return "secondary"
}

export const stepLabel = (step: SupportStepKind | string) =>
  MODE_LABELS[step] || step

export const modeShare = (value: number) => `${(value * 100).toFixed(1)}%`

export const formatDateTime = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : "—"

export const formatDuration = (value?: number | null) => {
  if (value === null || value === undefined) return "—"
  if (value < 1000) return `${value} мс`
  return `${(value / 1000).toFixed(2)} с`
}

export function ModeBadge({ mode }: { mode: string }) {
  return <Badge variant={modeVariant(mode)}>{mode}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={statusVariant(status)}>{statusLabel(status)}</Badge>
}

export function TagList({ tags }: { tags: string[] }) {
  if (!tags.length) return null
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <Badge key={tag} variant="outline" className="font-normal">
          {tag}
        </Badge>
      ))}
    </div>
  )
}

export function SourceList({ sources }: { sources: SourceAttribution[] }) {
  if (!sources.length) return null
  return (
    <div className="grid gap-2">
      <p className="text-xs font-medium uppercase text-muted-foreground">
        Источники
      </p>
      {sources.map((source) => (
        <div
          key={`${source.source_id}-${source.chunk_id || "none"}`}
          className="rounded-md border bg-muted/30 p-2 text-xs"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium">{source.source_title}</p>
            {source.score !== null && source.score !== undefined ? (
              <span className="shrink-0 text-muted-foreground">
                {source.score.toFixed(3)}
              </span>
            ) : null}
          </div>
          {source.source_ref ? (
            <a
              className="break-all text-primary underline"
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

export function StepsTimeline({ steps }: { steps: SupportStep[] }) {
  if (!steps.length) return null
  return (
    <div className="grid gap-2">
      <p className="text-xs font-medium uppercase text-muted-foreground">
        Шаги обработки
      </p>
      <ol className="grid gap-2">
        {steps.map((step) => (
          <li
            key={`${step.step}-${step.step_index}`}
            className="rounded-md border p-2 text-xs"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={modeVariant(step.step)}>{step.step}</Badge>
              <span className="text-muted-foreground">
                {stepLabel(step.step)}
              </span>
              {step.is_final ? (
                <Badge variant="secondary">финальный</Badge>
              ) : (
                <Badge variant="outline">ожидает оператора</Badge>
              )}
              <span className="text-muted-foreground">
                {formatDuration(step.response_time_ms)}
              </span>
              <span className="ml-auto text-muted-foreground">
                {formatDateTime(step.created_at)}
              </span>
            </div>
            <p className="mt-1 whitespace-pre-wrap">{step.answer}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function EmptyState({ text }: { text: string }) {
  return (
    <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
      {text}
    </p>
  )
}
