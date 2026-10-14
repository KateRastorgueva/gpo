import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { EllipsisVertical, Search } from "lucide-react"
import { useEffect, useState } from "react"

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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
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

const PAGE_SIZE = 25

// FAQ живёт на своей вкладке, поэтому по умолчанию здесь только документы.
const TYPE_FILTERS = [
  { value: "docs", label: "Документы и тексты" },
  { value: "pdf", label: "PDF" },
  { value: "url", label: "Страницы сайта" },
  { value: "manual", label: "Ручной текст" },
  { value: "faq", label: "FAQ" },
  { value: "all", label: "Все" },
]

const typeParams = (filter: string) =>
  filter === "docs"
    ? { exclude_type: "faq" }
    : filter === "all"
      ? {}
      : { source_type: filter }

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

  const [searchInput, setSearchInput] = useState("")
  const [search, setSearch] = useState("")
  const [typeFilter, setTypeFilter] = useState("docs")
  const [page, setPage] = useState(0)

  // Поиск уходит на сервер с задержкой, чтобы не дёргать API на каждую букву.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput)
      setPage(0)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  const sourcesQuery = useQuery({
    queryKey: ["adminSupportSources", search, typeFilter, page],
    queryFn: () =>
      getKnowledgeSources({
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
        ...typeParams(typeFilter),
      }),
    placeholderData: keepPreviousData,
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
  const total = sourcesQuery.data?.count ?? 0
  const pageCount = Math.ceil(total / PAGE_SIZE)
  const categories = categoriesQuery.data?.data ?? []

  return (
    <div className="grid gap-6">
      {canWrite ? (
        <details className="rounded-xl border bg-card">
          <summary className="cursor-pointer px-6 py-4 font-semibold">
            Добавить источник знаний
          </summary>
          <div className="grid gap-3 px-6 pb-6">
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
          </div>
        </details>
      ) : null}

      <Card className="min-w-0">
        <CardHeader className="grid gap-3">
          <div className="flex items-center justify-between gap-2">
            <CardTitle>Источники знаний</CardTitle>
            <span className="text-xs text-muted-foreground">
              найдено: {total}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-48 flex-1">
              <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Поиск по названию"
                className="pl-8"
              />
            </div>
            <Select
              value={typeFilter}
              onValueChange={(value) => {
                setTypeFilter(value)
                setPage(0)
              }}
            >
              <SelectTrigger className="w-52">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TYPE_FILTERS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="min-w-0">
          {sourcesQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : sources.length === 0 ? (
            <EmptyState text="Ничего не найдено." />
          ) : (
            <Table className="table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead>Источник</TableHead>
                  <TableHead className="hidden w-36 md:table-cell">
                    Категория
                  </TableHead>
                  <TableHead className="w-32">Статус</TableHead>
                  <TableHead className="w-14" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.map((source) => (
                  <TableRow key={source.id}>
                    <TableCell className="whitespace-normal">
                      <p
                        className="line-clamp-2 break-words font-medium"
                        title={source.title}
                      >
                        {source.title}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {source.source_type}
                        {source.is_active ? "" : " · снят с публикации"}
                        {source.source_ref && source.source_ref !== source.title
                          ? ` · ${source.source_ref}`
                          : ""}
                      </p>
                      {source.tags.length ? (
                        <div className="mt-1">
                          <TagList tags={source.tags} />
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell className="hidden whitespace-normal text-sm md:table-cell">
                      {source.category_name || "—"}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={source.status} />
                    </TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Действия"
                          >
                            <EllipsisVertical />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {canWrite ? (
                            <DropdownMenuItem onClick={() => openEdit(source)}>
                              Изменить
                            </DropdownMenuItem>
                          ) : null}
                          <DropdownMenuItem
                            onClick={() => setArchiveTarget(source)}
                          >
                            История версий
                          </DropdownMenuItem>
                          {canWrite ? (
                            <>
                              <DropdownMenuItem
                                onClick={() =>
                                  reindexMutation.mutate({
                                    sourceIds: [source.id],
                                  })
                                }
                              >
                                Переиндексировать
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                disabled={!source.is_active}
                                onClick={() =>
                                  deactivateMutation.mutate(source.id)
                                }
                              >
                                Снять с публикации
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                variant="destructive"
                                onClick={() => deleteMutation.mutate(source.id)}
                              >
                                Удалить
                              </DropdownMenuItem>
                            </>
                          ) : null}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {pageCount > 1 ? (
            <div className="mt-4 flex items-center justify-between gap-2 text-sm">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                Назад
              </Button>
              <span className="text-muted-foreground">
                страница {page + 1} из {pageCount}
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
