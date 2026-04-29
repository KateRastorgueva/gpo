import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getMyQueue } from "@/services/supportApi"

export const Route = createFileRoute("/_layout/my-requests")({
  component: MyRequestsPage,
  head: () => ({
    meta: [{ title: "Мои обращения" }],
  }),
})

const formatDate = (value?: string | null) => {
  if (!value) return ""
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function MyRequestsPage() {
  const myQueueQuery = useQuery({
    queryKey: ["myQueue"],
    queryFn: getMyQueue,
  })

  const items = myQueueQuery.data?.data ?? []

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Мои обращения к оператору</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          {myQueueQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Загрузка…</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              У вас пока нет обращений к оператору.
            </p>
          ) : (
            items.map((item) => {
              const hasReply = !!item.reply_text
              return (
                <div key={item.queue_id} className="rounded border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-medium">{item.question}</p>
                    <Badge variant={hasReply ? "secondary" : "destructive"}>
                      {hasReply ? "ответ получен" : item.status}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Причина эскалации: {item.reason}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Создано: {formatDate(item.created_at)}
                  </p>
                  {hasReply ? (
                    <div className="mt-2 rounded bg-muted p-2 text-sm">
                      <p className="text-xs text-muted-foreground">
                        Ответ оператора · {formatDate(item.reply_created_at)}
                      </p>
                      <p>{item.reply_text}</p>
                    </div>
                  ) : (
                    <p className="mt-2 text-xs text-muted-foreground">
                      Ответ оператора ещё не получен.
                    </p>
                  )}
                </div>
              )
            })
          )}
        </CardContent>
      </Card>
    </div>
  )
}
