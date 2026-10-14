import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Search } from "lucide-react"
import { useMemo, useState } from "react"

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

const PAGE_SIZE = 30

export function FaqPanel() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { has } = usePermissions()
  // Без knowledge:write записи доступны только на чтение
  const canWrite = has(PERMISSIONS.KNOWLEDGE_WRITE)
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState("")
  const [answer, setAnswer] = useState("")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(0)

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

  const allEntries = faqQuery.data?.data ?? []
  // Поиск по вопросу и ответу на клиенте: записей сотни, они уже загружены.
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!needle) return allEntries
    return allEntries.filter(
      (entry) =>
        entry.question.toLowerCase().includes(needle) ||
        entry.answer.toLowerCase().includes(needle),
    )
  }, [allEntries, search])
  const pageCount = Math.ceil(filtered.length / PAGE_SIZE)
  const entries = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

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
          <details className="rounded-md border">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
              Добавить запись
            </summary>
          <div className="grid gap-2 p-3 pt-0">
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
          </details>
        ) : null}

        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(0)
            }}
            placeholder="Поиск по вопросу или ответу"
            className="pl-8"
          />
        </div>

        {faqQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Загрузка...</p>
        ) : entries.length === 0 ? (
          <EmptyState text="Ничего не найдено." />
        ) : (
          <div className="grid gap-1">
            {entries.map((entry) => (
              <details key={entry.id} className="group rounded-md border">
                <summary className="flex cursor-pointer items-center gap-2 px-3 py-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">
                    {entry.question}
                  </span>
                  {entry.is_active ? null : (
                    <StatusBadge status="deleted" />
                  )}
                </summary>
                <div className="grid gap-2 border-t px-3 py-2">
                  <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                    {entry.answer}
                  </p>
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
              </details>
            ))}
          </div>
        )}
        {pageCount > 1 ? (
          <div className="flex items-center justify-between gap-2 text-sm">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              Назад
            </Button>
            <span className="text-muted-foreground">
              страница {page + 1} из {pageCount} · найдено {filtered.length}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page + 1 >= pageCount}
              onClick={() => setPage(page + 1)}
            >
              Дальше
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
