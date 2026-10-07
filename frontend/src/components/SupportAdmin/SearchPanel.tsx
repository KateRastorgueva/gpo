import { useMutation, useQuery } from "@tanstack/react-query"
import { Search } from "lucide-react"
import { useState } from "react"

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
  getCategories,
  getTags,
  type KnowledgeSearchHit,
  searchKnowledge,
} from "@/services/supportApi"

type OwnerType = "source" | "doc"

export function SearchPanel() {
  const { showErrorToast } = useCustomToast()
  const [question, setQuestion] = useState("")
  const [limit, setLimit] = useState("5")
  const [ownerTypes, setOwnerTypes] = useState<OwnerType[]>([])
  const [categoryId, setCategoryId] = useState("all")
  const [tagIds, setTagIds] = useState<string[]>([])
  const [hits, setHits] = useState<KnowledgeSearchHit[] | null>(null)

  const categoriesQuery = useQuery({
    queryKey: ["adminCategories"],
    queryFn: getCategories,
  })
  const tagsQuery = useQuery({
    queryKey: ["adminTags"],
    queryFn: getTags,
  })

  const searchMutation = useMutation({
    mutationFn: () =>
      searchKnowledge({
        question: question.trim(),
        owner_types: ownerTypes.length ? ownerTypes : undefined,
        category_ids: categoryId === "all" ? undefined : [categoryId],
        tag_ids: tagIds.length ? tagIds : undefined,
        limit: Number(limit),
      }),
    onSuccess: (data) => setHits(data.data),
    onError: (error: Error) => showErrorToast(error.message),
  })

  const toggleOwnerType = (value: OwnerType) =>
    setOwnerTypes((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    )

  const toggleTag = (value: string) =>
    setTagIds((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    )

  const categories = categoriesQuery.data?.data ?? []
  const tags = tagsQuery.data?.data ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle>Поиск по базе знаний</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <p className="text-xs text-muted-foreground">
          Фильтры применяются в векторном хранилище до отбора top-k, поэтому
          ограничение по категории или тэгу не теряет релевантные фрагменты.
        </p>
        <div className="flex flex-wrap gap-2">
          <Input
            className="min-w-[240px] flex-1"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Поисковый запрос"
            onKeyDown={(event) => {
              if (event.key === "Enter" && question.trim()) {
                searchMutation.mutate()
              }
            }}
          />
          <Select value={limit} onValueChange={setLimit}>
            <SelectTrigger className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {["3", "5", "10", "20"].map((value) => (
                <SelectItem key={value} value={value}>
                  top-{value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <LoadingButton
            loading={searchMutation.isPending}
            disabled={!question.trim()}
            onClick={() => searchMutation.mutate()}
          >
            <Search className="size-4" />
            Найти
          </LoadingButton>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="grid gap-1">
            <Label>Корпус</Label>
            <div className="flex gap-2">
              {(["source", "doc"] as OwnerType[]).map((value) => (
                <Button
                  key={value}
                  size="sm"
                  variant={ownerTypes.includes(value) ? "default" : "outline"}
                  onClick={() => toggleOwnerType(value)}
                >
                  {value === "source" ? "источники" : "документы"}
                </Button>
              ))}
            </div>
          </div>
          <div className="grid gap-1">
            <Label>Категория</Label>
            <Select value={categoryId} onValueChange={setCategoryId}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все категории</SelectItem>
                {categories.map((category) => (
                  <SelectItem key={category.id} value={category.id}>
                    {category.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1">
            <Label>Тэги</Label>
            <div className="flex flex-wrap gap-1">
              {tags.length === 0 ? (
                <span className="text-xs text-muted-foreground">нет тэгов</span>
              ) : null}
              {tags.map((tag) => (
                <Badge
                  key={tag.id}
                  variant={tagIds.includes(tag.id) ? "default" : "outline"}
                  className="cursor-pointer font-normal"
                  onClick={() => toggleTag(tag.id)}
                >
                  {tag.name}
                </Badge>
              ))}
            </div>
          </div>
        </div>

        {hits === null ? null : hits.length === 0 ? (
          <EmptyState text="Ничего не найдено по заданным фильтрам." />
        ) : (
          <div className="grid gap-2">
            <p className="text-xs text-muted-foreground">
              Найдено фрагментов: {hits.length}
            </p>
            {hits.map((hit) => (
              <div
                key={`${hit.chunk_id || hit.source_id}-${hit.score}`}
                className="rounded-md border p-3 text-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium">{hit.source_title}</p>
                  <Badge variant="secondary">{hit.score.toFixed(3)}</Badge>
                </div>
                {hit.source_ref ? (
                  <a
                    className="text-xs break-all text-primary underline"
                    href={hit.source_ref}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {hit.source_ref}
                  </a>
                ) : null}
                {hit.snippet ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {hit.snippet}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
