import { useQuery } from "@tanstack/react-query"
import { Star } from "lucide-react"

import { modeShare } from "@/components/Support/display"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getSupportMetrics } from "@/services/supportApi"

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-semibold">{value}</p>
    </div>
  )
}

export function MetricsPanel() {
  const metricsQuery = useQuery({
    queryKey: ["adminSupportMetrics"],
    queryFn: getSupportMetrics,
  })
  const metrics = metricsQuery.data

  return (
    <Card>
      <CardHeader>
        <CardTitle>Метрики поддержки</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {metricsQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Загрузка метрик...</p>
        ) : null}
        {metrics ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                label="Всего запросов"
                value={String(metrics.total_requests)}
              />
              <Metric label="Доля FAQ" value={modeShare(metrics.faq_share)} />
              <Metric label="Доля RAG" value={modeShare(metrics.rag_share)} />
              <Metric
                label="Доля оператора"
                value={modeShare(metrics.operator_share)}
              />
              <Metric
                label="Средняя уверенность"
                value={metrics.average_confidence.toFixed(2)}
              />
              <Metric
                label="Ответы без источников"
                value={modeShare(metrics.empty_sources_share)}
              />
              <Metric label="Отзывов" value={String(metrics.feedback_count)} />
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">Средняя оценка</p>
                <div className="flex items-center gap-2">
                  <p className="text-xl font-semibold">
                    {metrics.average_rating
                      ? metrics.average_rating.toFixed(2)
                      : "—"}
                  </p>
                  {metrics.average_rating ? (
                    <span className="flex items-center">
                      {[1, 2, 3, 4, 5].map((value) => (
                        <Star
                          key={value}
                          className={
                            value <= Math.round(metrics.average_rating)
                              ? "size-4 fill-primary text-primary"
                              : "size-4 text-muted-foreground"
                          }
                        />
                      ))}
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Отзыв считается один раз на запрос; оценка по шкале 1–5.
            </p>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
