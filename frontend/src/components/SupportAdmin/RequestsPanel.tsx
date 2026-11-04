import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import {
  EmptyState,
  formatDateTime,
  ModeBadge,
  StatusBadge,
} from "@/components/Support/display"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import { getActiveRequests, getJournalRequests } from "@/services/supportApi"

const STATUS_OPTIONS = [
  { value: "all", label: "Все статусы" },
  { value: "queued", label: "В очереди" },
  { value: "in_progress", label: "В работе" },
  { value: "answered", label: "Отвечены" },
  { value: "closed", label: "Закрыты" },
]

export function RequestsPanel() {
  const [status, setStatus] = useState("all")

  const activeQuery = useQuery({
    queryKey: ["adminActiveRequests"],
    queryFn: () => getActiveRequests({ limit: 50 }),
  })
  const journalQuery = useQuery({
    queryKey: ["adminJournalRequests", status],
    queryFn: () =>
      getJournalRequests({
        status: status === "all" ? undefined : status,
        limit: 50,
      }),
  })

  const active = activeQuery.data?.data ?? []
  const journal = journalQuery.data?.data ?? []

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Активная очередь</CardTitle>
          <span className="text-xs text-muted-foreground">
            {activeQuery.data?.count ?? 0} в работе
          </span>
        </CardHeader>
        <CardContent>
          {activeQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : active.length === 0 ? (
            <EmptyState text="Очередь пуста — все запросы обработаны." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Вопрос</TableHead>
                  <TableHead className="w-32">Канал</TableHead>
                  <TableHead className="w-32">Приоритет</TableHead>
                  <TableHead className="w-48">В очереди с</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {active.map((item) => (
                  <TableRow key={item.request_id}>
                    <TableCell className="max-w-md truncate">
                      {item.question}
                    </TableCell>
                    <TableCell>{item.channel}</TableCell>
                    <TableCell>{item.priority}</TableCell>
                    <TableCell>{formatDateTime(item.queued_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle>Журнал запросов</CardTitle>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent>
          {journalQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : journal.length === 0 ? (
            <EmptyState text="Запросов с таким статусом нет." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Вопрос</TableHead>
                  <TableHead className="w-40">Тема</TableHead>
                  <TableHead className="w-24">Режим</TableHead>
                  <TableHead className="w-32">Статус</TableHead>
                  <TableHead className="w-28">Уверенность</TableHead>
                  <TableHead className="w-48">Создан</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {journal.map((item) => (
                  <TableRow key={item.request_id}>
                    <TableCell className="max-w-md truncate">
                      {item.question}
                    </TableCell>
                    <TableCell className="text-sm">
                      {item.intent_label ?? (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <ModeBadge mode={item.mode} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={item.status} />
                    </TableCell>
                    <TableCell>{item.confidence.toFixed(2)}</TableCell>
                    <TableCell>{formatDateTime(item.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
