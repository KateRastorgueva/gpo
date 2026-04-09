import { OpenAPI } from "@/client"

export type SourceAttribution = {
  source_id: string
  source_title: string
  source_ref?: string | null
  chunk_id?: string | null
  snippet?: string | null
  score?: number | null
}

export type DecisionMetrics = {
  top_score: number
  relevant_chunks: number
  faq_score: number
  conflict: boolean
  critical: boolean
}

export type SupportAskResponse = {
  request_id: string
  session_id: string
  mode: "faq" | "rag" | "operator"
  answer: string
  sources: SourceAttribution[]
  confidence: number
  escalated: boolean
  fallback_used: boolean
  route_reason: string
  decision_metrics: DecisionMetrics
}

export type SupportHistoryEntry = {
  request_id: string
  question: string
  mode: "faq" | "rag" | "operator"
  answer: string
  sources: SourceAttribution[]
  confidence: number
  escalated: boolean
  fallback_used: boolean
  created_at?: string | null
}

export type FaqEntry = {
  id: string
  question: string
  answer: string
  is_active: boolean
  created_at?: string | null
  updated_at?: string | null
}

export type KnowledgeSource = {
  id: string
  title: string
  source_type: "pdf" | "txt" | "url" | "manual"
  source_ref?: string | null
  is_active: boolean
  status: "pending" | "indexed" | "failed"
  last_indexed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type OperatorQueueEntry = {
  queue_id: string
  request_id: string
  reason: string
  status: "open" | "in_progress" | "closed"
  question: string
  created_at?: string | null
}

export type SupportMetrics = {
  total_requests: number
  faq_share: number
  rag_share: number
  operator_share: number
  average_confidence: number
  empty_sources_share: number
}

const jsonHeaders = () => ({
  "Content-Type": "application/json",
  Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
})

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const base = OpenAPI.BASE || ""
  const response = await fetch(`${base}${path}`, init)
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      localStorage.removeItem("access_token")
      window.location.href = "/login"
    }
    let detail = "Request failed"
    try {
      const body = await response.json()
      detail = body?.detail || detail
    } catch {
      // no-op
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export const askSupport = (payload: {
  question: string
  session_id: string
  channel: "web"
}) =>
  request<SupportAskResponse>("/api/v1/support/ask", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })

export const getSupportHistory = (sessionId: string) =>
  request<{ data: SupportHistoryEntry[]; count: number }>(
    `/api/v1/support/history?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: "GET",
      headers: { Authorization: jsonHeaders().Authorization },
    },
  )

export const getFaqEntries = () =>
  request<{ data: FaqEntry[]; count: number }>("/api/v1/admin/faq", {
    method: "GET",
    headers: { Authorization: jsonHeaders().Authorization },
  })

export const createFaqEntry = (payload: {
  question: string
  answer: string
  is_active: boolean
}) =>
  request<FaqEntry>("/api/v1/admin/faq", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })

export const updateFaqEntry = (
  faqId: string,
  payload: { question?: string; answer?: string; is_active?: boolean },
) =>
  request<FaqEntry>(`/api/v1/admin/faq/${faqId}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })

export const deleteFaqEntry = (faqId: string) =>
  request<{ message: string }>(`/api/v1/admin/faq/${faqId}`, {
    method: "DELETE",
    headers: { Authorization: jsonHeaders().Authorization },
  })

export const getKnowledgeSources = () =>
  request<{ data: KnowledgeSource[]; count: number }>("/api/v1/admin/sources", {
    method: "GET",
    headers: { Authorization: jsonHeaders().Authorization },
  })

export const uploadKnowledgeSource = (payload: {
  title?: string
  source_url?: string
  manual_content?: string
  file?: File
}) => {
  const formData = new FormData()
  if (payload.title) formData.set("title", payload.title)
  if (payload.source_url) formData.set("source_url", payload.source_url)
  if (payload.manual_content) {
    formData.set("manual_content", payload.manual_content)
  }
  if (payload.file) formData.set("file", payload.file)
  return request<KnowledgeSource>("/api/v1/admin/sources/upload", {
    method: "POST",
    headers: { Authorization: jsonHeaders().Authorization },
    body: formData,
  })
}

export const reindexKnowledgeSources = (options?: {
  sourceIds?: string[]
  fullRebuild?: boolean
  purgeOrphans?: boolean
}) =>
  request<{
    message: string
    reindexed_sources: number
    orphan_vectors_removed: number
    full_rebuild: boolean
  }>(
    "/api/v1/admin/sources/reindex",
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        source_ids: options?.sourceIds,
        full_rebuild: options?.fullRebuild ?? false,
        purge_orphans: options?.purgeOrphans ?? true,
      }),
    },
  )

export const getOperatorQueue = () =>
  request<{ data: OperatorQueueEntry[]; count: number }>(
    "/api/v1/admin/operator-queue",
    {
      method: "GET",
      headers: { Authorization: jsonHeaders().Authorization },
    },
  )

export const getSupportMetrics = () =>
  request<SupportMetrics>("/api/v1/admin/metrics", {
    method: "GET",
    headers: { Authorization: jsonHeaders().Authorization },
  })
