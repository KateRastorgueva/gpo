import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw, Upload } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { EmptyState, formatDateTime } from "@/components/Support/display"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import usePermissions from "@/hooks/usePermissions"
import { PERMISSIONS } from "@/lib/permissions"
import {
  createIngestJob,
  getEngineDocuments,
  getIngestJobs,
  getRagProvider,
  type IngestItem,
  type IngestJob,
  type IngestTarget,
  type RagEngine,
  type RagProviderName,
  setRagProvider,
  uploadIngestFile,
} from "@/services/supportApi"

const TARGET_LABELS: Record<IngestTarget, string> = {
  both: "Оба движка",
  gemini: "Только Gemini (облако)",
  anythingllm: "Только AnythingLLM (локально)",
  local: "Встроенная база (для «Только поиск»)",
}

const ENGINE_STATUS: Record<
  string,
  {
    label: string
    variant: "default" | "secondary" | "destructive" | "outline"
  }
> = {
  ok: { label: "загружен", variant: "default" },
  already: { label: "уже был", variant: "secondary" },
  "no-text": { label: "нет текста (скан)", variant: "outline" },
  error: { label: "ошибка", variant: "destructive" },
}

const ITEM_STATUS: Record<IngestItem["status"], string> = {
  queued: "в очереди",
  running: "обрабатывается",
  done: "готово",
  failed: "ошибка",
}

const formatEta = (seconds?: number | null) => {
  if (!seconds) return null
  const minutes = Math.floor(seconds / 60)
  return minutes ? `≈ ${minutes} мин ${seconds % 60} с` : `≈ ${seconds} с`
}

const formatSize = (bytes?: number | null) =>
  bytes == null ? "—" : `${(bytes / 1024 / 1024).toFixed(1)} МБ`

function EngineStatus({ status }: { status?: string | null }) {
  if (!status) return <span className="text-muted-foreground">—</span>
  const meta = ENGINE_STATUS[status] || {
    label: status,
    variant: "outline" as const,
  }
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}

function ProviderCard({ canWrite }: { canWrite: boolean }) {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const providerQuery = useQuery({
    queryKey: ["ragProvider"],
    queryFn: getRagProvider,
  })
  const mutation = useMutation({
    mutationFn: (provider: RagProviderName) => setRagProvider(provider),
    onSuccess: (data) => {
      queryClient.setQueryData(["ragProvider"], data)
      showSuccessToast("Движок переключён, новые вопросы идут через него")
    },
    onError: (error: Error) => showErrorToast(error.message),
  })
  const state = providerQuery.data

  return (
    <Card>
      <CardHeader>
        <CardTitle>Движок ответов</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-sm text-muted-foreground">
          Через какой движок отвечать после FAQ. Переключение действует сразу,
          без перезапуска.
        </p>
        <div className="flex flex-wrap gap-2">
          {state?.options.map((option) => (
            <Button
              key={option.name}
              variant={state.active === option.name ? "default" : "outline"}
              disabled={!canWrite || !option.configured || mutation.isPending}
              title={
                option.configured
                  ? undefined
                  : "Не настроен: задайте ключ во вкладке «Настройки»"
              }
              onClick={() => mutation.mutate(option.name)}
            >
              {option.label}
            </Button>
          ))}
        </div>
        {state ? (
          <p className="text-xs text-muted-foreground">
            По умолчанию из .env: {state.default}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

const providerTarget = (provider?: RagProviderName): IngestTarget =>
  provider === "gemini_file_search"
    ? "gemini"
    : provider === "anythingllm"
      ? "anythingllm"
      : "local"

export function UploadCard({
  onStarted,
  title = "Загрузка документов в движки",
}: {
  onStarted: () => void
  title?: string
}) {
  const providerQuery = useQuery({
    queryKey: ["ragProvider"],
    queryFn: getRagProvider,
  })
  const [targetTouched, setTargetTouched] = useState(false)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [files, setFiles] = useState<File[]>([])
  const [target, setTarget] = useState<IngestTarget>("both")
  const [sent, setSent] = useState(0)
  const [busy, setBusy] = useState(false)

  // По умолчанию грузим в активный движок, пока пользователь не выбрал сам
  useEffect(() => {
    if (!targetTouched && providerQuery.data) {
      setTarget(providerTarget(providerQuery.data.active))
    }
  }, [providerQuery.data, targetTouched])

  const start = async () => {
    if (!files.length) return
    setBusy(true)
    setSent(0)
    const failed: string[] = []
    try {
      const job = await createIngestJob(target, files.length)
      onStarted()
      // По одному файлу на запрос: прокси пропускает не больше 25 МБ за раз.
      for (const file of files) {
        try {
          await uploadIngestFile(job.id, file)
        } catch (error) {
          failed.push(`${file.name}: ${(error as Error).message}`)
        }
        setSent((value) => value + 1)
        onStarted()
      }
      if (failed.length) {
        showErrorToast(`Не отправлены: ${failed.join("; ")}`)
      } else {
        showSuccessToast("Файлы отправлены, индексация идёт в фоне")
      }
      setFiles([])
    } catch (error) {
      showErrorToast((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="grid gap-3 md:grid-cols-[1fr_260px]">
          <div className="grid gap-2">
            <Label htmlFor="ingest-files">Файлы (можно выбрать много)</Label>
            <button
              type="button"
              className={`flex cursor-pointer flex-col items-center justify-center rounded-md border border-dashed px-3 py-4 text-center text-sm text-muted-foreground transition-colors ${
                dragging ? "border-primary bg-muted" : ""
              }`}
              onClick={() => !busy && inputRef.current?.click()}
              onDragOver={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                if (!busy) setFiles(Array.from(event.dataTransfer.files))
              }}
            >
              <Upload className="mb-1 size-4" />
              {files.length
                ? files.length <= 3
                  ? files.map((file) => file.name).join(", ")
                  : `Выбрано файлов: ${files.length}`
                : "Перетащите файлы сюда или нажмите, чтобы выбрать"}
            </button>
            <Input
              ref={inputRef}
              id="ingest-files"
              className="hidden"
              type="file"
              multiple
              accept=".pdf,.docx,.doc,.txt,.md,.html,.xlsx,.pptx"
              disabled={busy}
              onChange={(event) =>
                setFiles(Array.from(event.target.files || []))
              }
            />
          </div>
          <div className="grid gap-2">
            <Label>Куда загрузить</Label>
            <Select
              value={target}
              onValueChange={(value) => {
                setTargetTouched(true)
                setTarget(value as IngestTarget)
              }}
              disabled={busy}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(TARGET_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Gemini распознаёт сканы сам (OCR). AnythingLLM берёт только текстовый
          слой — у сканов будет статус «нет текста». Файлы с тем же именем, что
          уже есть в движке, пропускаются. Встроенная база (Postgres) берёт
          текстовый слой PDF, а также .txt/.md/.html; файл с тем же именем
          заменяется новой версией.
        </p>
        <div className="flex items-center gap-3">
          <LoadingButton
            loading={busy}
            disabled={!files.length}
            onClick={start}
          >
            <Upload />
            {files.length
              ? `Загрузить ${files.length} файл(ов)`
              : "Выберите файлы"}
          </LoadingButton>
          {busy ? (
            <span className="text-sm text-muted-foreground">
              Отправлено {sent} из {files.length}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

export function JobCard({ job }: { job: IngestJob }) {
  const processed = job.done + job.failed
  const percent = Math.round((processed / job.total) * 100)
  const eta = formatEta(job.eta_seconds)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Загрузка от {formatDateTime(job.created_at)}
          <Badge variant="outline">{TARGET_LABELS[job.target]}</Badge>
          {job.finished ? (
            <Badge variant={job.failed ? "destructive" : "default"}>
              {job.failed ? `завершена, ошибок: ${job.failed}` : "завершена"}
            </Badge>
          ) : (
            <Badge variant="secondary">идёт</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="grid gap-1">
          <div className="h-2 w-full overflow-hidden rounded bg-muted">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${percent}%` }}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            Обработано {processed} из {job.total} (успешно {job.done}, ошибок{" "}
            {job.failed}); на сервере {job.uploaded} из {job.total}
            {eta && !job.finished ? `; осталось ${eta}` : ""}
          </p>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Файл</TableHead>
                <TableHead>Размер</TableHead>
                <TableHead>Статус</TableHead>
                <TableHead>Gemini</TableHead>
                <TableHead>AnythingLLM</TableHead>
                <TableHead>Встроенная</TableHead>
                <TableHead>Ошибка</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {job.items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="max-w-[320px] truncate">
                    {item.filename}
                  </TableCell>
                  <TableCell>{formatSize(item.size_bytes)}</TableCell>
                  <TableCell>{ITEM_STATUS[item.status]}</TableCell>
                  <TableCell>
                    <EngineStatus status={item.gemini_status} />
                  </TableCell>
                  <TableCell>
                    <EngineStatus status={item.anythingllm_status} />
                  </TableCell>
                  <TableCell>
                    <EngineStatus status={item.local_status} />
                  </TableCell>
                  <TableCell className="max-w-[320px] whitespace-pre-wrap text-xs text-destructive">
                    {item.error}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function EngineDocumentsCard() {
  const [engine, setEngine] = useState<RagEngine>("gemini")
  const docsQuery = useQuery({
    queryKey: ["engineDocuments", engine],
    queryFn: () => getEngineDocuments(engine),
  })
  const docs = docsQuery.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Документы в движке
          <Button
            size="sm"
            variant={engine === "gemini" ? "default" : "outline"}
            onClick={() => setEngine("gemini")}
          >
            Gemini
          </Button>
          <Button
            size="sm"
            variant={engine === "anythingllm" ? "default" : "outline"}
            onClick={() => setEngine("anythingllm")}
          >
            AnythingLLM
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => docsQuery.refetch()}
            disabled={docsQuery.isFetching}
          >
            <RefreshCw className={docsQuery.isFetching ? "animate-spin" : ""} />
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {docsQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Загрузка списка...</p>
        ) : null}
        {docs && !docs.configured ? (
          <EmptyState text="Движок не настроен: задайте ключ во вкладке «Настройки»" />
        ) : null}
        {docs?.error ? (
          <p className="text-sm text-destructive">{docs.error}</p>
        ) : null}
        {docs?.configured && !docs.error ? (
          <>
            <p className="text-sm text-muted-foreground">
              Всего документов: {docs.count}
            </p>
            <div className="max-h-[420px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Название</TableHead>
                    <TableHead>Состояние</TableHead>
                    <TableHead>Размер</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {docs.data.map((doc) => (
                    <TableRow key={doc.name}>
                      <TableCell className="max-w-[420px] truncate">
                        {doc.name}
                      </TableCell>
                      <TableCell>{doc.state || "—"}</TableCell>
                      <TableCell>
                        {doc.size_bytes != null
                          ? formatSize(doc.size_bytes)
                          : doc.word_count != null
                            ? `${doc.word_count.toLocaleString("ru-RU")} слов`
                            : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

// Вкладка «Движок»: выбор движка и то, что в нём лежит.
// Загрузка файлов живёт в «Документы», чтобы не было двух мест для одного.
export function EnginesPanel() {
  const { has } = usePermissions()
  const canWrite = has(PERMISSIONS.KNOWLEDGE_WRITE)
  const jobsQuery = useQuery({
    queryKey: ["ingestJobs"],
    queryFn: getIngestJobs,
    refetchInterval: (query) =>
      query.state.data?.data.some((job) => !job.finished) ? 2500 : false,
  })
  const latest = jobsQuery.data?.data[0]

  return (
    <div className="grid gap-4">
      <ProviderCard canWrite={canWrite} />
      {latest ? <JobCard job={latest} /> : null}
      <EngineDocumentsCard />
    </div>
  )
}
