import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, RotateCcw, Upload } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { EmptyState } from "@/components/Support/display"
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
import useCustomToast from "@/hooks/useCustomToast"
import {
  type AppSettingField,
  type AppSettingsState,
  exportAppSettings,
  getAppSettings,
  importAppSettings,
  settingsFieldErrors,
  updateAppSettings,
} from "@/services/supportApi"

const QUERY_KEY = ["appSettings"]

const asText = (value: AppSettingField["value"]) =>
  value === null || value === undefined ? "" : String(value)

/** Черновик формы: для обычных полей — текущее значение, для ключей — пусто. */
const draftFrom = (state: AppSettingsState) => {
  const draft: Record<string, string> = {}
  for (const group of state.groups) {
    for (const field of group.fields) {
      draft[field.key] = field.kind === "secret" ? "" : asText(field.value)
    }
  }
  return draft
}

function SourceBadge({ field }: { field: AppSettingField }) {
  if (field.kind === "secret") {
    if (field.source === "admin") return <Badge>задан в админке</Badge>
    if (field.source === "env")
      return <Badge variant="secondary">из .env</Badge>
    return <Badge variant="outline">не задан</Badge>
  }
  return field.overridden ? (
    <Badge>изменено</Badge>
  ) : (
    <Badge variant="secondary">из .env</Badge>
  )
}

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: AppSettingField
  value: string
  onChange: (value: string) => void
}) {
  const id = `setting-${field.key}`
  if (field.kind === "choice" || field.kind === "bool") {
    const choices =
      field.kind === "bool"
        ? [
            { value: "true", label: "включено" },
            { value: "false", label: "выключено" },
          ]
        : field.choices.map((choice) => ({ value: choice, label: choice }))
    return (
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {choices.map((choice) => (
            <SelectItem key={choice.value} value={choice.value}>
              {choice.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }
  if (field.kind === "secret") {
    return (
      <Input
        id={id}
        type="password"
        autoComplete="off"
        placeholder={
          field.is_set
            ? `сохранён (${field.hint ?? "…"}), введите новый, чтобы заменить`
            : "вставьте ключ"
        }
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }
  const numeric = field.kind === "int" || field.kind === "float"
  return (
    <Input
      id={id}
      inputMode={numeric ? "decimal" : undefined}
      type={field.kind === "url" ? "url" : "text"}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

export function SettingsPanel() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const fileInput = useRef<HTMLInputElement>(null)
  const settingsQuery = useQuery({
    queryKey: QUERY_KEY,
    queryFn: getAppSettings,
  })
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    if (settingsQuery.data) setDraft(draftFrom(settingsQuery.data))
  }, [settingsQuery.data])

  const applyState = (state: AppSettingsState) => {
    queryClient.setQueryData(QUERY_KEY, state)
    // Ключи и выбор движка влияют на вкладку «Движки RAG».
    queryClient.invalidateQueries({ queryKey: ["ragProvider"] })
    setErrors({})
  }

  const onError = (error: Error) => {
    const fieldErrors = settingsFieldErrors(error)
    setErrors(fieldErrors)
    showErrorToast(
      Object.keys(fieldErrors).length
        ? "Проверьте отмеченные поля, ничего не сохранено"
        : error.message,
    )
  }

  const fields = settingsQuery.data?.groups.flatMap((g) => g.fields) ?? []
  const changes: Record<string, string> = {}
  for (const field of fields) {
    const value = draft[field.key] ?? ""
    if (field.kind === "secret") {
      if (value.trim()) changes[field.key] = value.trim()
    } else if (value !== asText(field.value)) {
      changes[field.key] = value
    }
  }
  const dirty = Object.keys(changes).length > 0

  const saveMutation = useMutation({
    mutationFn: () => updateAppSettings({ values: changes }),
    onSuccess: (data) => {
      applyState(data)
      showSuccessToast("Сохранено, действует без перезапуска")
    },
    onError,
  })

  const resetMutation = useMutation({
    mutationFn: (key: string) => updateAppSettings({ reset: [key] }),
    onSuccess: (data) => {
      applyState(data)
      showSuccessToast("Возвращено значение из .env")
    },
    onError,
  })

  const importMutation = useMutation({
    mutationFn: (text: string) => importAppSettings(text),
    onSuccess: (data) => {
      applyState(data)
      const ignored = data.ignored.length
        ? `; пропущено: ${data.ignored.join(", ")}`
        : ""
      showSuccessToast(`Загружено настроек: ${data.applied.length}${ignored}`)
    },
    onError,
  })

  const exportMutation = useMutation({
    mutationFn: exportAppSettings,
    onSuccess: (text) => {
      const blob = new Blob([text], { type: "application/yaml" })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = "ksup-settings.yaml"
      link.click()
      URL.revokeObjectURL(url)
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const onFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (file) importMutation.mutate(await file.text())
  }

  if (settingsQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Загрузка настроек...</p>
  }
  if (!settingsQuery.data) {
    return <EmptyState text="Не удалось загрузить настройки" />
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 pt-6">
          <p className="mr-auto max-w-2xl text-sm text-muted-foreground">
            Значения из .env действуют, пока их не изменили здесь. Изменения
            применяются сразу, без перезапуска. Ключи хранятся в базе
            зашифрованными и в YAML-выгрузку не попадают.
          </p>
          <Button
            variant="outline"
            onClick={() => exportMutation.mutate()}
            disabled={exportMutation.isPending}
          >
            <Download className="mr-2 h-4 w-4" />
            Скачать YAML
          </Button>
          <Button
            variant="outline"
            onClick={() => fileInput.current?.click()}
            disabled={importMutation.isPending}
          >
            <Upload className="mr-2 h-4 w-4" />
            Загрузить YAML
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept=".yaml,.yml,text/yaml,application/yaml"
            className="hidden"
            onChange={onFile}
          />
        </CardContent>
      </Card>

      {settingsQuery.data.groups.map((group) => (
        <Card key={group.id}>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-baseline gap-2">
              {group.label}
              <code className="text-xs font-normal text-muted-foreground">
                {group.id}
              </code>
            </CardTitle>
            {group.help ? (
              <p className="text-sm text-muted-foreground">{group.help}</p>
            ) : null}
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {group.fields.map((field) => {
              const error = errors[field.key] || field.error
              const canReset = field.overridden
              return (
                <div
                  key={field.key}
                  className="grid min-w-0 content-start gap-1.5"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Label htmlFor={`setting-${field.key}`}>
                      {field.label}
                    </Label>
                    <SourceBadge field={field} />
                    {canReset ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-xs"
                        title="Вернуть значение из .env"
                        disabled={resetMutation.isPending}
                        onClick={() => resetMutation.mutate(field.key)}
                      >
                        <RotateCcw className="mr-1 h-3 w-3" />
                        сбросить
                      </Button>
                    ) : null}
                  </div>
                  <FieldInput
                    field={field}
                    value={draft[field.key] ?? ""}
                    onChange={(value) =>
                      setDraft((current) => ({
                        ...current,
                        [field.key]: value,
                      }))
                    }
                  />
                  {error ? (
                    <p className="text-xs text-destructive">{error}</p>
                  ) : null}
                  <p className="text-xs text-muted-foreground">
                    {field.help}
                    {field.kind !== "secret" &&
                    field.overridden &&
                    field.default !== null &&
                    field.default !== undefined
                      ? ` В .env: ${field.default}.`
                      : ""}
                  </p>
                </div>
              )
            })}
          </CardContent>
        </Card>
      ))}

      <div className="sticky bottom-0 flex flex-wrap items-center justify-end gap-3 border-t bg-background py-3">
        {dirty ? (
          <span className="text-sm text-muted-foreground">
            Изменено полей: {Object.keys(changes).length}
          </span>
        ) : null}
        <Button
          variant="outline"
          disabled={!dirty || saveMutation.isPending}
          onClick={() => {
            setDraft(draftFrom(settingsQuery.data))
            setErrors({})
          }}
        >
          Отменить
        </Button>
        <LoadingButton
          loading={saveMutation.isPending}
          disabled={!dirty}
          onClick={() => saveMutation.mutate()}
        >
          Сохранить
        </LoadingButton>
      </div>
    </div>
  )
}
