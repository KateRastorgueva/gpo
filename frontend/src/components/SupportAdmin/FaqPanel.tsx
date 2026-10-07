import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { EmptyState, StatusBadge } from "@/components/Support/display"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import usePermissions from "@/hooks/usePermissions"
import { PERMISSIONS } from "@/lib/permissions"
import {
  createFaqEntry,
  deleteFaqEntry,
  getFaqEntries,
  updateFaqEntry,
} from "@/services/supportApi"

export function FaqPanel() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { has } = usePermissions()
  // Без knowledge:write записи доступны только на чтение
  const canWrite = has(PERMISSIONS.KNOWLEDGE_WRITE)
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState("")
  const [answer, setAnswer] = useState("")

  const faqQuery = useQuery({
    queryKey: ["adminSupportFaq"],
    queryFn: getFaqEntries,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["adminSupportFaq"] })
    queryClient.invalidateQueries({ queryKey: ["adminSupportSources"] })
    queryClient.invalidateQueries({ queryKey: ["adminSupportMetrics"] })
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createFaqEntry({
        question: question.trim(),
        answer: answer.trim(),
        is_active: true,
      }),
    onSuccess: () => {
      setQuestion("")
      setAnswer("")
      showSuccessToast("Запись добавлена в базу знаний")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const toggleMutation = useMutation({
    mutationFn: (payload: { id: string; isActive: boolean }) =>
      updateFaqEntry(payload.id, { is_active: payload.isActive }),
    onSuccess: () => {
      showSuccessToast("Статус записи обновлён")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (faqId: string) => deleteFaqEntry(faqId),
    onSuccess: () => {
      showSuccessToast("Запись удалена")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const entries = faqQuery.data?.data ?? []

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Частые вопросы</CardTitle>
        <span className="text-xs text-muted-foreground">
          {faqQuery.data?.count ?? 0} записей
        </span>
      </CardHeader>
      <CardContent className="grid gap-4">
        <p className="text-xs text-muted-foreground">
          Записи хранятся в базе знаний с типом <code>faq</code>: их можно
          фильтровать по категориям и тэгам на вкладке «База знаний».
        </p>
        {canWrite ? (
          <div className="grid gap-2">
            <Input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Вопрос"
            />
            <Textarea
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              rows={3}
              placeholder="Ответ"
            />
            <div className="flex justify-end">
              <LoadingButton
                loading={createMutation.isPending}
                disabled={!question.trim() || !answer.trim()}
                onClick={() => createMutation.mutate()}
              >
                Добавить запись
              </LoadingButton>
            </div>
          </div>
        ) : null}

        {faqQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Загрузка...</p>
        ) : entries.length === 0 ? (
          <EmptyState text="Записей нет — добавьте первую пару вопрос/ответ." />
        ) : (
          <div className="grid gap-2">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className="flex flex-wrap items-start justify-between gap-3 rounded-md border p-3"
              >
                <div className="grid gap-1">
                  <p className="text-sm font-medium">{entry.question}</p>
                  <p className="text-sm text-muted-foreground">
                    {entry.answer}
                  </p>
                  <StatusBadge
                    status={entry.is_active ? "indexed" : "deleted"}
                  />
                </div>
                {canWrite ? (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={toggleMutation.isPending}
                      onClick={() =>
                        toggleMutation.mutate({
                          id: entry.id,
                          isActive: !entry.is_active,
                        })
                      }
                    >
                      {entry.is_active ? "Скрыть" : "Опубликовать"}
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={deleteMutation.isPending}
                      onClick={() => deleteMutation.mutate(entry.id)}
                    >
                      Удалить
                    </Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
