import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { useState } from "react"

import { UsersService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  createFaqEntry,
  deleteFaqEntry,
  getFaqEntries,
  getKnowledgeSources,
  getOperatorQueue,
  getSupportMetrics,
  reindexKnowledgeSources,
  uploadKnowledgeSource,
} from "@/services/supportApi"

export const Route = createFileRoute("/_layout/admin-support")({
  component: AdminSupportPage,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({
    meta: [{ title: "Support Admin - FastAPI Template" }],
  }),
})

function AdminSupportPage() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [faqQuestion, setFaqQuestion] = useState("")
  const [faqAnswer, setFaqAnswer] = useState("")
  const [sourceTitle, setSourceTitle] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [manualContent, setManualContent] = useState("")
  const [sourceFile, setSourceFile] = useState<File | null>(null)

  const faqQuery = useQuery({
    queryKey: ["adminSupportFaq"],
    queryFn: getFaqEntries,
  })
  const sourcesQuery = useQuery({
    queryKey: ["adminSupportSources"],
    queryFn: getKnowledgeSources,
  })
  const queueQuery = useQuery({
    queryKey: ["adminSupportQueue"],
    queryFn: getOperatorQueue,
  })
  const metricsQuery = useQuery({
    queryKey: ["adminSupportMetrics"],
    queryFn: getSupportMetrics,
  })

  const createFaqMutation = useMutation({
    mutationFn: () =>
      createFaqEntry({
        question: faqQuestion,
        answer: faqAnswer,
        is_active: true,
      }),
    onSuccess: () => {
      setFaqQuestion("")
      setFaqAnswer("")
      showSuccessToast("FAQ добавлен")
      queryClient.invalidateQueries({ queryKey: ["adminSupportFaq"] })
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const deleteFaqMutation = useMutation({
    mutationFn: (faqId: string) => deleteFaqEntry(faqId),
    onSuccess: () => {
      showSuccessToast("FAQ удален")
      queryClient.invalidateQueries({ queryKey: ["adminSupportFaq"] })
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const uploadSourceMutation = useMutation({
    mutationFn: () =>
      uploadKnowledgeSource({
        title: sourceTitle || undefined,
        source_url: sourceUrl || undefined,
        manual_content: manualContent || undefined,
        file: sourceFile || undefined,
      }),
    onSuccess: () => {
      setSourceTitle("")
      setSourceUrl("")
      setManualContent("")
      setSourceFile(null)
      showSuccessToast("Источник загружен")
      queryClient.invalidateQueries({ queryKey: ["adminSupportSources"] })
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const reindexMutation = useMutation({
    mutationFn: () => reindexKnowledgeSources(),
    onSuccess: (data) => {
      showSuccessToast(
        `Переиндексировано: ${data.reindexed_sources}, удалено сиротских векторов: ${data.orphan_vectors_removed}`,
      )
      queryClient.invalidateQueries({ queryKey: ["adminSupportSources"] })
      queryClient.invalidateQueries({ queryKey: ["adminSupportMetrics"] })
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const fullRebuildMutation = useMutation({
    mutationFn: () =>
      reindexKnowledgeSources({ fullRebuild: true, purgeOrphans: true }),
    onSuccess: (data) => {
      showSuccessToast(
        `Полная пересборка завершена: ${data.reindexed_sources}, удалено сиротских векторов: ${data.orphan_vectors_removed}`,
      )
      queryClient.invalidateQueries({ queryKey: ["adminSupportSources"] })
      queryClient.invalidateQueries({ queryKey: ["adminSupportMetrics"] })
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Метрики поддержки</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          <p>
            Всего запросов:{" "}
            <span className="font-medium">
              {metricsQuery.data?.total_requests ?? 0}
            </span>
          </p>
          <p>
            Доли режимов: FAQ{" "}
            <span className="font-medium">
              {((metricsQuery.data?.faq_share ?? 0) * 100).toFixed(1)}%
            </span>
            {" | "}RAG{" "}
            <span className="font-medium">
              {((metricsQuery.data?.rag_share ?? 0) * 100).toFixed(1)}%
            </span>
            {" | "}Operator{" "}
            <span className="font-medium">
              {((metricsQuery.data?.operator_share ?? 0) * 100).toFixed(1)}%
            </span>
          </p>
          <p>
            Средняя уверенность:{" "}
            <span className="font-medium">
              {(metricsQuery.data?.average_confidence ?? 0).toFixed(2)}
            </span>
          </p>
          <p>
            Пустые источники в ответах:{" "}
            <span className="font-medium">
              {((metricsQuery.data?.empty_sources_share ?? 0) * 100).toFixed(1)}%
            </span>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>FAQ</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <Input
            value={faqQuestion}
            onChange={(event) => setFaqQuestion(event.target.value)}
            placeholder="Вопрос FAQ"
          />
          <textarea
            value={faqAnswer}
            onChange={(event) => setFaqAnswer(event.target.value)}
            placeholder="Ответ FAQ"
            rows={3}
            className="w-full rounded-md border bg-background p-3 text-sm"
          />
          <LoadingButton
            loading={createFaqMutation.isPending}
            onClick={() => createFaqMutation.mutate()}
          >
            Добавить FAQ
          </LoadingButton>
          <div className="grid gap-2">
            {faqQuery.data?.data.map((faq) => (
              <div
                key={faq.id}
                className="flex items-start justify-between gap-3 rounded border p-3"
              >
                <div>
                  <p className="text-sm font-medium">{faq.question}</p>
                  <p className="text-sm text-muted-foreground">{faq.answer}</p>
                </div>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => deleteFaqMutation.mutate(faq.id)}
                  disabled={deleteFaqMutation.isPending}
                >
                  Удалить
                </Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Источники знаний</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <Input
            value={sourceTitle}
            onChange={(event) => setSourceTitle(event.target.value)}
            placeholder="Название источника"
          />
          <Input
            value={sourceUrl}
            onChange={(event) => setSourceUrl(event.target.value)}
            placeholder="URL источника (опционально)"
          />
          <textarea
            value={manualContent}
            onChange={(event) => setManualContent(event.target.value)}
            placeholder="Ручной текст источника (опционально)"
            rows={4}
            className="w-full rounded-md border bg-background p-3 text-sm"
          />
          <Input
            type="file"
            onChange={(event) => setSourceFile(event.target.files?.[0] || null)}
          />
          <div className="flex gap-2">
            <LoadingButton
              loading={uploadSourceMutation.isPending}
              onClick={() => uploadSourceMutation.mutate()}
            >
              Загрузить источник
            </LoadingButton>
            <LoadingButton
              loading={reindexMutation.isPending}
              onClick={() => reindexMutation.mutate()}
              variant="outline"
            >
              Reindex
            </LoadingButton>
            <LoadingButton
              loading={fullRebuildMutation.isPending}
              onClick={() => fullRebuildMutation.mutate()}
              variant="outline"
            >
              Полная пересборка
            </LoadingButton>
          </div>
          <div className="grid gap-2">
            {sourcesQuery.data?.data.map((source) => (
              <div key={source.id} className="rounded border p-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">{source.title}</p>
                  <Badge variant="secondary">{source.status}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {source.source_type} {source.source_ref ? `| ${source.source_ref}` : ""}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Очередь оператора</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2">
          {queueQuery.data?.data.length ? (
            queueQuery.data.data.map((item) => (
              <div key={item.queue_id} className="rounded border p-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">{item.question}</p>
                  <Badge variant="destructive">{item.status}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  Причина: {item.reason}
                </p>
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">Очередь пуста</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
