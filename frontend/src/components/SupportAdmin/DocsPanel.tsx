import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { EmptyState, StatusBadge, TagList } from "@/components/Support/display"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
  createKnowledgeDoc,
  deleteKnowledgeDoc,
  getKnowledgeDocs,
  type KnowledgeDoc,
  reindexKnowledgeDocs,
  updateKnowledgeDoc,
} from "@/services/supportApi"

const parseTags = (value: string) =>
  value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean)

export function DocsPanel() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { has } = usePermissions()
  // Без knowledge:write корпус документов доступен только на чтение
  const canWrite = has(PERMISSIONS.KNOWLEDGE_WRITE)
  const queryClient = useQueryClient()

  const [title, setTitle] = useState("")
  const [url, setUrl] = useState("")
  const [tags, setTags] = useState("")

  const [editTarget, setEditTarget] = useState<KnowledgeDoc | null>(null)
  const [editTitle, setEditTitle] = useState("")
  const [editUrl, setEditUrl] = useState("")
  const [editTags, setEditTags] = useState("")

  const docsQuery = useQuery({
    queryKey: ["adminDocs"],
    queryFn: getKnowledgeDocs,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["adminDocs"] })
    queryClient.invalidateQueries({ queryKey: ["adminSupportMetrics"] })
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createKnowledgeDoc({
        title: title.trim(),
        url: url.trim(),
        tags: parseTags(tags),
      }),
    onSuccess: () => {
      setTitle("")
      setUrl("")
      setTags("")
      showSuccessToast("Документ добавлен и проиндексирован")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const updateMutation = useMutation({
    mutationFn: (doc: KnowledgeDoc) =>
      updateKnowledgeDoc(doc.id, {
        title: editTitle.trim(),
        url: editUrl.trim(),
        tags: parseTags(editTags),
      }),
    onSuccess: () => {
      showSuccessToast("Документ обновлён")
      setEditTarget(null)
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (docId: string) => deleteKnowledgeDoc(docId),
    onSuccess: () => {
      showSuccessToast("Документ удалён")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const reindexMutation = useMutation({
    mutationFn: (docIds?: string[]) =>
      reindexKnowledgeDocs({ docIds, purgeOrphans: true }),
    onSuccess: (data) => {
      showSuccessToast(
        `Переиндексировано документов: ${data.reindexed_docs}, удалено сиротских векторов: ${data.orphan_vectors_removed}`,
      )
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const openEdit = (doc: KnowledgeDoc) => {
    setEditTarget(doc)
    setEditTitle(doc.title)
    setEditUrl(doc.url)
    setEditTags(doc.tags.join(", "))
  }

  const docs = docsQuery.data?.data ?? []

  return (
    <div className="grid gap-6">
      {canWrite ? (
        <Card>
          <CardHeader>
            <CardTitle>Новый документ</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            <p className="text-xs text-muted-foreground">
              Документы — независимый корпус: содержимое забирается по ссылке и
              индексируется отдельно от источников.
            </p>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Название документа"
            />
            <Input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="Ссылка на документ (PDF/HTML)"
            />
            <Input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder="Тэги через запятую (опционально)"
            />
            <div className="flex flex-wrap gap-2">
              <LoadingButton
                loading={createMutation.isPending}
                disabled={!title.trim() || !url.trim()}
                onClick={() => createMutation.mutate()}
              >
                Добавить документ
              </LoadingButton>
              <LoadingButton
                variant="outline"
                loading={reindexMutation.isPending}
                onClick={() => reindexMutation.mutate(undefined)}
              >
                Переиндексировать документы
              </LoadingButton>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Документы</CardTitle>
          <span className="text-xs text-muted-foreground">
            {docsQuery.data?.count ?? 0} всего
          </span>
        </CardHeader>
        <CardContent>
          {docsQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : docs.length === 0 ? (
            <EmptyState text="Документов нет — добавьте первый." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Документ</TableHead>
                  <TableHead className="w-40">Тэги</TableHead>
                  <TableHead className="w-32">Статус</TableHead>
                  <TableHead className="w-56">Действия</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {docs.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell>
                      <p className="font-medium">{doc.title}</p>
                      <a
                        className="text-xs break-all text-primary underline"
                        href={doc.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {doc.url}
                      </a>
                    </TableCell>
                    <TableCell>
                      <TagList tags={doc.tags} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={doc.status} />
                    </TableCell>
                    <TableCell>
                      {canWrite ? (
                        <div className="flex flex-wrap gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEdit(doc)}
                          >
                            Изменить
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => reindexMutation.mutate([doc.id])}
                          >
                            Reindex
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={deleteMutation.isPending}
                            onClick={() => deleteMutation.mutate(doc.id)}
                          >
                            Удалить
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          только чтение
                        </span>
                      )}
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
            <DialogTitle>Документ</DialogTitle>
            <DialogDescription>
              Если изменить ссылку, документ будет переиндексирован при
              следующем reindex.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1">
              <Label htmlFor="doc-title">Название</Label>
              <Input
                id="doc-title"
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="doc-url">Ссылка</Label>
              <Input
                id="doc-url"
                value={editUrl}
                onChange={(event) => setEditUrl(event.target.value)}
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="doc-tags">Тэги (через запятую)</Label>
              <Input
                id="doc-tags"
                value={editTags}
                onChange={(event) => setEditTags(event.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <LoadingButton
              loading={updateMutation.isPending}
              disabled={!editTitle.trim() || !editUrl.trim()}
              onClick={() => editTarget && updateMutation.mutate(editTarget)}
            >
              Сохранить
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
