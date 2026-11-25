import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import type { SourceAttribution } from "@/services/supportApi"

interface MessageProps {
  type: "user" | "bot"
  content: string
  mode?: string
  confidence?: number
  sources?: SourceAttribution[]
  createdAt?: string
}

const MODE_LABELS: Record<string, string> = {
  faq: "Ответ из FAQ",
  rag: "Ответ по документам",
  operator: "Передано оператору",
  human: "Ответ оператора",
}

const modeVariant = (mode: string) => {
  if (mode === "faq" || mode === "human") return "default"
  if (mode === "rag") return "secondary"
  return "outline"
}

const formatTime = (value?: string) =>
  value
    ? new Date(value).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null

// Модели отвечают в markdown. Полноценный парсер не нужен: хватает жирного
// текста, заголовков и списков; HTML не вставляем, только React-узлы.
const inline = (text: string): ReactNode[] =>
  text
    .split(/(\*\*[^*]+\*\*)/g)
    .filter(Boolean)
    .map((part, index) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : (
        part.replace(/`/g, "")
      ),
    )

function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: ReactNode[] = []
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={`l${blocks.length}`} className="my-1 list-disc pl-5">
          {list}
        </ul>,
      )
      list = []
    }
  }
  text.split("\n").forEach((raw, index) => {
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*(?:[*-]|\d+\.)\s+(.*)$/)
    if (bullet) {
      list.push(<li key={index}>{inline(bullet[1])}</li>)
      return
    }
    flush()
    if (!line.trim()) return
    const heading = line.match(/^#{1,6}\s+(.*)$/)
    blocks.push(
      <p key={index} className={heading ? "mt-2 font-semibold" : "mt-1"}>
        {inline(heading ? heading[1] : line)}
      </p>,
    )
  })
  flush()
  return <div className="text-sm [&>*:first-child]:mt-0">{blocks}</div>
}

const isLink = (value?: string | null) =>
  !!value && (value.startsWith("http://") || value.startsWith("https://"))

export function Message({
  type,
  content,
  mode,
  confidence,
  sources,
  createdAt,
}: MessageProps) {
  const time = formatTime(createdAt)

  if (type === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-primary-foreground">
          <p className="whitespace-pre-wrap text-sm">{content}</p>
          {time ? <p className="mt-1 text-right text-xs opacity-70">{time}</p> : null}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-2xl rounded-bl-sm border bg-card px-4 py-3">
        {mode ? (
          <Badge variant={modeVariant(mode)} className="mb-2">
            {MODE_LABELS[mode] ?? mode}
          </Badge>
        ) : null}
        <RichText text={content} />
        {sources && sources.length > 0 ? (
          // open: ссылки на источники видны сразу, без клика по свёрнутому блоку.
          <details className="mt-2 text-xs" open>
            <summary className="cursor-pointer text-muted-foreground">
              {mode === "operator" ? "Возможный контекст" : "Источники"} (
              {sources.length})
              {confidence !== undefined && mode !== "faq"
                ? ` · уверенность ${Math.round(confidence * 100)}%`
                : ""}
            </summary>
            <div className="mt-2 grid gap-2">
              {sources.map((source, index) => (
                <div
                  key={`${source.source_id}-${source.chunk_id ?? index}`}
                  className="rounded border p-2"
                >
                  <p className="font-medium">{source.source_title}</p>
                  {isLink(source.source_ref) ? (
                    <a
                      className="break-all text-primary underline"
                      href={source.source_ref as string}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {source.source_ref}
                    </a>
                  ) : source.source_ref ? (
                    // PDF и файлы корпуса: ссылки нет, но видно, откуда взят ответ.
                    <p className="break-all text-muted-foreground">
                      файл: {source.source_ref}
                    </p>
                  ) : null}
                  {source.snippet ? (
                    <p className="mt-1 text-muted-foreground">{source.snippet}</p>
                  ) : null}
                </div>
              ))}
            </div>
          </details>
        ) : null}
        {time ? <p className="mt-1 text-xs text-muted-foreground">{time}</p> : null}
      </div>
    </div>
  )
}
