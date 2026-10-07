import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import {
  EmptyState,
  formatDateTime,
  StatusBadge,
  TagList,
} from "@/components/Support/display"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import usePermissions from "@/hooks/usePermissions"
import { PERMISSIONS } from "@/lib/permissions"
import {
  deactivateKnowledgeSource,
  deleteKnowledgeSource,
  getCategories,
  getKnowledgeSources,
  getSourceArchive,
  type KnowledgeSource,
  reindexKnowledgeSources,
  updateKnowledgeSource,
  uploadKnowledgeSource,
} from "@/services/supportApi"

const parseTags = (value: string) =>
  value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean)

export function KnowledgePanel() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { has } = usePermissions()
  // Без knowledge:write источники доступны только на чтение (история версий — чтение)
  const canWrite = has(PERMISSIONS.KNOWLEDGE_WRITE)
  const queryClient = useQueryClient()

  const [title, setTitle] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [manualContent, setManualContent] = useState("")
  const [file, setFile] = useState<File | null>(null)

  const [editTarget, setEditTarget] = useState<KnowledgeSource | null>(null)
  const [editTitle, setEditTitle] = useState("")
  const [editCategory, setEditCategory] = useState("none")
  const [editTags, setEditTags] = useState("")
  const [editActive, setEditActive] = useState(true)

  const [archiveTarget, setArchiveTarget] = useState<KnowledgeSource | null>(
    null,
  )

  const sourcesQuery = useQuery({
    queryKey: ["adminSupportSources"],
    queryFn: getKnowledgeSources,
  })
  const categoriesQuery = useQuery({
    queryKey: ["adminCategories"],
    queryFn: getCategories,
  })
  const archiveQuery = useQuery({
    queryKey: ["adminSourceArchive", archiveTarget?.id],
    queryFn: () => getSourceArchive(archiveTarget?.id as string),
    enabled: archiveTarget !== null,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["adminSupportSources"] })
    queryClient.invalidateQueries({ queryKey: ["adminSupportMetrics"] })
  }

  const uploadMutation = useMutation({
    mutationFn: () =>
      uploadKnowledgeSource({
        title: title || undefined,
        source_url: sourceUrl || undefined,
        manual_content: manualContent || undefined,
        file: file || undefined,
      }),
    onSuccess: () => {
      setTitle("")
      setSourceUrl("")
      setManualContent("")
      setFile(null)
      showSuccessToast("Источник добавлен и проиндексирован")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const updateMutation = useMutation({
    mutationFn: (source: KnowledgeSource) =>
      updateKnowledgeSource(source.id, {
        title: editTitle,
        category_id: editCategory === "none" ? null : editCategory,
        tags: parseTags(editTags),
        is_active: editActive,
      }),
    onSuccess: () => {
      showSuccessToast("Источник обновлён, версия сохранена в архив")
      setEditTarget(null)
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const deactivateMutation = useMutation({
    mutationFn: (sourceId: string) => deactivateKnowledgeSource(sourceId),
    onSuccess: () => {
      showSuccessToast("Источник снят с публикации, история сохранена")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (sourceId: string) => deleteKnowledgeSource(sourceId),
    onSuccess: () => {
      showSuccessToast("Источник удалён вместе с архивом версий")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const reindexMutation = useMutation({
    mutationFn: (options: { sourceIds?: string[]; fullRebuild?: boolean }) =>
      reindexKnowledgeSources(options),
    onSuccess: (data) => {
      showSuccessToast(
        `Переиндексировано источников: ${data.reindexed_sources}, документов: ${data.reindexed_docs}, удалено сиротских векторов: ${data.orphan_vectors_removed}`,
      )
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const openEdit = (source: KnowledgeSource) => {
    setEditTarget(source)
    setEditTitle(source.title)
    setEditCategory(source.category_id ?? "none")
    setEditTags(source.tags.join(", "))
    setEditActive(source.is_active)
  }

  const sources = sourcesQuery.data?.data ?? []
  const categories = categoriesQuery.data?.data ?? []

  return (
    <div className="grid gap-6">
      {canWrite ? (
        <Card>
          <CardHeader>
            <CardTitle>Новый источник знаний</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Название источника"
            />
            <Input
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
              placeholder="URL страницы (опционально)"
            />
            <Textarea
              value={manualContent}
              onChange={(event) => setManualContent(event.target.value)}
              rows={4}
              placeholder="Или вставьте текст вручную"
            />
            <Input
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
            <div className="flex flex-wrap gap-2">
              <LoadingButton
                loading={uploadMutation.isPending}
                onClick={() => uploadMutation.mutate()}
              >
                Добавить источник
              </LoadingButton>
              <LoadingButton
                variant="outline"
                loading={reindexMutation.isPending}
                onClick={() => reindexMutation.mutate({})}
              >
                Переиндексировать источники
              </LoadingButton>
              <LoadingButton
                variant="outline"
                loading={reindexMutation.isPending}
                onClick={() => reindexMutation.mutate({ fullRebuild: true })}
              >
                Полная пересборка (оба корпуса)
              </LoadingButton>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Источники знаний</CardTitle>
          <span className="text-xs text-muted-foreground">
            {sourcesQuery.data?.count ?? 0} всего
          </span>
        </CardHeader>
        <CardContent>
          {sourcesQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : sources.length === 0 ? (
            <EmptyState text="Источников нет — добавьте первый." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Источник</TableHead>
                  <TableHead className="w-32">Категория</TableHead>
                  <TableHead className="w-40">Тэги</TableHead>
                  <TableHead className="w-32">Статус</TableHead>
                  <TableHead className="w-56">Действия</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.map((source) => (
                  <TableRow key={source.id}>
                    <TableCell>
                      <p className="font-medium">{source.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {source.source_type}
                        {source.source_ref ? ` · ${source.source_ref}` : ""}
                        {source.is_active ? "" : " · снят с публикации"}
                      </p>
                    </TableCell>
                    <TableCell className="text-sm">
                      {source.category_name || "—"}
                    </TableCell>
                    <TableCell>
                      <TagList tags={source.tags} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={source.status} />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {canWrite ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEdit(source)}
                          >
                            Изменить
                          </Button>
                        ) : null}
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setArchiveTarget(source)}
                        >
                          История
                        </Button>
                        {canWrite ? (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                reindexMutation.mutate({
                                  sourceIds: [source.id],
                                })
                              }
                            >
                              Reindex
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={
                                deactivateMutation.isPending ||
                                !source.is_active
                              }
                              onClick={() =>
                                deactivateMutation.mutate(source.id)
                              }
                            >
                              Скрыть
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              disabled={deleteMutation.isPending}
                              onClick={() => deleteMutation.mutate(source.id)}
                            >
                              Удалить
                            </Button>
                          </>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={editTarget !== null}
        onOpenChange={(open) => {
          if (!open) setEditTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Метаданные источника</DialogTitle>
            <DialogDescription>
              Перед сохранением текущая версия попадёт в архив. Тэги появятся в
              фильтрах поиска сразу, без переиндексации.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1">
              <Label htmlFor="source-title">Название</Label>
              <Input
                id="source-title"
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
              />
            </div>
            <div className="grid gap-1">
              <Label>Категория</Label>
              <Select value={editCategory} onValueChange={setEditCategory}>
                <SelectTrigger>
                  <SelectValue placeholder="Без категории" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Без категории</SelectItem>
                  {categories.map((category) => (
                    <SelectItem key={category.id} value={category.id}>
                      {category.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1">
              <Label htmlFor="source-tags">Тэги (через запятую)</Label>
              <Input
                id="source-tags"
                value={editTags}
                onChange={(event) => setEditTags(event.target.value)}
                placeholder="поступление, общежитие"
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="source-active"
                checked={editActive}
                onCheckedChange={(checked) => setEditActive(checked === true)}
              />
              <Label htmlFor="source-active">
                Опубликован (участвует в поиске)
              </Label>
            </div>
          </div>
          <DialogFooter>
            <LoadingButton
              loading={updateMutation.isPending}
              disabled={!editTitle.trim()}
              onClick={() => editTarget && updateMutation.mutate(editTarget)}
            >
              Сохранить
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={archiveTarget !== null}
        onOpenChange={(open) => {
          if (!open) setArchiveTarget(null)
        }}
      >
        <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>История версий</DialogTitle>
            <DialogDescription>
              {archiveTarget?.title}. Снапшоты создаются при изменении
              метаданных и при снятии с публикации.
            </DialogDescription>
          </DialogHeader>
          {archiveQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : archiveQuery.data?.data.length ? (
            <div className="grid gap-3">
              {archiveQuery.data.data.map((entry) => (
                <div key={entry.id} className="rounded-md border p-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Версия {entry.version}</span>
                    {entry.tags.length ? <TagList tags={entry.tags} /> : null}
                    <span className="ml-auto text-muted-foreground">
                      {formatDateTime(entry.archived_at)}
                    </span>
                  </div>
                  <p className="mt-1 font-medium">{entry.title}</p>
                  <p className="mt-1 whitespace-pre-wrap text-muted-foreground">
                    {entry.content.length > 400
                      ? `${entry.content.slice(0, 400)}…`
                      : entry.content}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState text="Версий пока нет — источник ещё не менялся." />
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
