import { useQuery } from "@tanstack/react-query"

import { OpenAPI } from "@/client"
import { request as __request } from "@/client/core/request"
import { isLoggedIn } from "@/hooks/useAuth"

type VersionInfo = {
  git_sha_short: string
  git_branch: string
  build_time: string
  rag_provider: string
  vector_search_enabled: boolean
  offtopic_filter_enabled: boolean
}

const onOff = (value: boolean) => (value ? "вкл" : "выкл")

export function formatBuildTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`
}

/** Малая строка о том, какую сборку мы смотрим (коммит, ветка, режимы RAG). */
export function BuildVersion({ className }: { className?: string }) {
  const { data } = useQuery({
    queryKey: ["build-version"],
    queryFn: () =>
      __request<VersionInfo>(OpenAPI, {
        method: "GET",
        url: "/api/v1/utils/version",
      }),
    staleTime: 60_000,
    retry: false,
    // Эндпоинт закрыт авторизацией: без входа не запрашиваем (иначе 401 на /login)
    enabled: isLoggedIn(),
  })

  if (!data) return null
  return (
    <p
      className={`text-xs text-muted-foreground ${className ?? ""}`}
      data-testid="build-version"
    >
      {data.git_sha_short} · {data.git_branch} ·{" "}
      {formatBuildTime(data.build_time)} · RAG: {data.rag_provider} · вектор:{" "}
      {onOff(data.vector_search_enabled)} · офтоп:{" "}
      {onOff(data.offtopic_filter_enabled)}
    </p>
  )
}
