import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { EmptyState, formatDateTime } from "@/components/Support/display"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import usePermissions from "@/hooks/usePermissions"
import { PERMISSIONS } from "@/lib/permissions"
import {
  createCategory,
  createTag,
  deleteCategory,
  deleteTag,
  getCategories,
  getTags,
  updateCategory,
} from "@/services/supportApi"

export function TaxonomyPanel() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { has } = usePermissions()
  // Без taxonomy:write справочники доступны только на чтение
  const canWrite = has(PERMISSIONS.TAXONOMY_WRITE)
  const queryClient = useQueryClient()
  const [categoryName, setCategoryName] = useState("")
  const [tagName, setTagName] = useState("")

  const categoriesQuery = useQuery({
    queryKey: ["adminCategories"],
    queryFn: getCategories,
  })
  const tagsQuery = useQuery({
    queryKey: ["adminTags"],
    queryFn: getTags,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["adminCategories"] })
    queryClient.invalidateQueries({ queryKey: ["adminTags"] })
    queryClient.invalidateQueries({ queryKey: ["adminSupportSources"] })
  }

  const createCategoryMutation = useMutation({
    mutationFn: () => createCategory(categoryName.trim()),
    onSuccess: () => {
      setCategoryName("")
      showSuccessToast("Категория добавлена")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const renameCategoryMutation = useMutation({
    mutationFn: (payload: { id: string; name: string }) =>
      updateCategory(payload.id, payload.name),
    onSuccess: () => {
      showSuccessToast("Категория переименована")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const deleteCategoryMutation = useMutation({
    mutationFn: (categoryId: string) => deleteCategory(categoryId),
    onSuccess: () => {
      showSuccessToast("Категория удалена (у источников она снята)")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const createTagMutation = useMutation({
    mutationFn: () => createTag(tagName.trim()),
    onSuccess: () => {
      setTagName("")
      showSuccessToast("Тэг добавлен")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const deleteTagMutation = useMutation({
    mutationFn: (tagId: string) => deleteTag(tagId),
    onSuccess: () => {
      showSuccessToast("Тэг удалён")
      invalidate()
    },
    onError: (error: Error) => showErrorToast(error.message),
  })

  const categories = categoriesQuery.data?.data ?? []
  const tags = tagsQuery.data?.data ?? []

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Категории знаний</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <p className="text-xs text-muted-foreground">
            Категория одна на источник (1:N). При удалении категории источник
            остаётся, но без категории.
          </p>
          {canWrite ? (
            <div className="flex gap-2">
              <Input
                value={categoryName}
                onChange={(event) => setCategoryName(event.target.value)}
                placeholder="Название категории"
              />
              <LoadingButton
                loading={createCategoryMutation.isPending}
                disabled={!categoryName.trim()}
                onClick={() => createCategoryMutation.mutate()}
              >
                Добавить
              </LoadingButton>
            </div>
          ) : null}
          {categoriesQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : categories.length === 0 ? (
            <EmptyState text="Категорий нет." />
          ) : (
            <div className="grid gap-2">
              {categories.map((category) => (
                <div
                  key={category.id}
                  className="flex flex-wrap items-center gap-2 rounded-md border p-2"
                >
                  <Input
                    className="h-8 max-w-[220px]"
                    defaultValue={category.name}
                    readOnly={!canWrite}
                    onBlur={(event) => {
                      const next = event.target.value.trim()
                      if (canWrite && next && next !== category.name) {
                        renameCategoryMutation.mutate({
                          id: category.id,
                          name: next,
                        })
                      }
                    }}
                  />
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(category.created_at)}
                  </span>
                  {canWrite ? (
                    <Button
                      className="ml-auto"
                      size="sm"
                      variant="destructive"
                      disabled={deleteCategoryMutation.isPending}
                      onClick={() => deleteCategoryMutation.mutate(category.id)}
                    >
                      Удалить
                    </Button>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Тэги</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <p className="text-xs text-muted-foreground">
            Тэги связывают источники и документы (M:N). Имена приводятся к
            нижнему регистру.
          </p>
          {canWrite ? (
            <div className="flex gap-2">
              <Input
                value={tagName}
                onChange={(event) => setTagName(event.target.value)}
                placeholder="Название тэга"
              />
              <LoadingButton
                loading={createTagMutation.isPending}
                disabled={!tagName.trim()}
                onClick={() => createTagMutation.mutate()}
              >
                Добавить
              </LoadingButton>
            </div>
          ) : null}
          {tagsQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : tags.length === 0 ? (
            <EmptyState text="Тэгов нет." />
          ) : (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <span
                  key={tag.id}
                  className="flex items-center gap-2 rounded-full border px-3 py-1 text-sm"
                >
                  <Badge variant="outline" className="font-normal">
                    {tag.name}
                  </Badge>
                  {canWrite ? (
                    <button
                      type="button"
                      className="text-xs text-muted-foreground hover:text-destructive"
                      onClick={() => deleteTagMutation.mutate(tag.id)}
                    >
                      удалить
                    </button>
                  ) : null}
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
