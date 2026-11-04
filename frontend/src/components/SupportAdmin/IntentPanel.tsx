import { useMutation, useQuery } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"
import { useState } from "react"

import { modeShare } from "@/components/Support/display"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { getIntentStatus, testIntent } from "@/services/supportApi"

// Классификатор тем (модель Кати): здесь состояние сервиса и проверка вопроса.
// Включение, порог и адрес — во вкладке «Настройки → Классификатор тем».
export function IntentPanel() {
  const [question, setQuestion] = useState("")
  const statusQuery = useQuery({
    queryKey: ["intentStatus"],
    queryFn: getIntentStatus,
  })
  const test = useMutation({ mutationFn: testIntent })
  const status = statusQuery.data

  let stateBadge = <Badge variant="outline">Проверяю…</Badge>
  if (status) {
    if (!status.reachable) {
      stateBadge = <Badge variant="destructive">Сервис недоступен</Badge>
    } else if (!status.model_loaded) {
      stateBadge = <Badge variant="destructive">Модель не загружена</Badge>
    } else {
      stateBadge = <Badge>Работает</Badge>
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <CardTitle>Классификатор тем</CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={() => statusQuery.refetch()}
          >
            <RefreshCw className="size-4" />
            Обновить
          </Button>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm">
          <p className="text-muted-foreground">
            Модель называет тему вопроса (стипендия, общежитие, ГПО…). Тема
            пишется в журнал, показывается в тикетах и метриках. На ответ
            пользователю не влияет.
          </p>
          {status ? (
            <div className="grid gap-1">
              <div className="flex flex-wrap items-center gap-2">
                {stateBadge}
                <Badge variant={status.enabled ? "default" : "outline"}>
                  {status.enabled ? "Включён" : "Выключен"}
                </Badge>
                <span className="text-muted-foreground">
                  порог {status.threshold.toFixed(2)} · {status.service_url}
                </span>
              </div>
              {status.error ? (
                <p className="text-xs text-destructive break-all">
                  {status.error}
                </p>
              ) : null}
              {!status.reachable ? (
                <p className="text-xs text-muted-foreground">
                  Запуск:{" "}
                  <code>docker compose --profile intent up -d intent</code>
                </p>
              ) : null}
              <p className="text-xs text-muted-foreground">
                Включить и поменять порог — «Настройки → Классификатор тем».
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Проверить вопрос</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              if (question.trim()) test.mutate(question.trim())
            }}
          >
            <Input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Как получить справку о стипендии?"
            />
            <LoadingButton type="submit" loading={test.isPending}>
              Проверить
            </LoadingButton>
          </form>
          {test.data ? (
            <div className="grid gap-1 text-sm">
              {test.data.error ? (
                <p className="text-destructive break-all">{test.data.error}</p>
              ) : (
                <p>
                  Тема:{" "}
                  <span className="font-medium">
                    {test.data.intent_label ?? "не определена (ниже порога)"}
                  </span>
                </p>
              )}
              {test.data.candidates.map((item) => (
                <div
                  key={item.category}
                  className="grid grid-cols-[1fr_auto] gap-3 rounded-md border px-3 py-1.5"
                >
                  <span>{item.label}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {modeShare(item.confidence)}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Проверка работает и при выключенном классификаторе и ничего не пишет
            в журнал.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
