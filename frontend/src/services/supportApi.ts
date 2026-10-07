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

export type SupportRouteMode = "faq" | "rag" | "operator"
export type SupportStepKind = SupportRouteMode | "human"

export type SupportStep = {
  step: SupportStepKind
  step_index: number
  answer: string
  is_final: boolean
  performed_by?: string | null
  knowledge_id?: string | null
  knowledge_chunk_id?: string | null
  response_time_ms?: number | null
  sources: SourceAttribution[]
  created_at?: string | null
}

export type SupportAskResponse = {
  request_id: string
  session_id: string
  mode: SupportRouteMode
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
  mode: SupportRouteMode
  answer: string
  sources: SourceAttribution[]
  confidence: number
  escalated: boolean
  fallback_used: boolean
  status: string
  created_at?: string | null
  steps: SupportStep[]
}

export type SupportFeedback = {
  id: string
  request_id: string
  user_id?: string | null
  rating: number
  comment?: string | null
  submitted_at: string
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
  source_type: string
  source_ref?: string | null
  is_active: boolean
  status: string
  category_id?: string | null
  category_name?: string | null
  tags: string[]
  last_indexed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type KnowledgeCategory = {
  id: string
  name: string
  created_at?: string | null
}

export type KnowledgeTag = {
  id: string
  name: string
  created_at?: string | null
}

export type KnowledgeDoc = {
  id: string
  title: string
  url: string
  status: string
  tags: string[]
  last_indexed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type KnowledgeArchiveEntry = {
  id: string
  knowledge_id: string
  version: number
  title: string
  content: string
  category_id?: string | null
  tags: string[]
  source_type: string
  archived_at: string
  archived_by?: string | null
}

export type KnowledgeSearchHit = {
  source_id: string
  source_title: string
  source_ref?: string | null
  chunk_id?: string | null
  snippet?: string | null
  score: number
}

export type SupportTicket = {
  ticket_id: string
  request_id: string
  reason: string
  status: string
  question: string
  assigned_to?: string | null
  resolution?: string | null
  reopened_from_id?: string | null
  created_at?: string | null
  resolved_at?: string | null
}

export type MyQueueEntry = {
  queue_id: string
  request_id: string
  question: string
  reason: string
  status: string
  created_at?: string | null
  reply_text?: string | null
  reply_created_at?: string | null
}

export type ActiveRequest = {
  request_id: string
  user_id?: string | null
  question: string
  channel: string
  priority: number
  assigned_to?: string | null
  queued_at: string
  updated_at?: string | null
}

export type JournalRequest = {
  request_id: string
  user_id?: string | null
  question: string
  channel: string
  mode: string
  status: string
  confidence: number
  escalated: boolean
  created_at?: string | null
  answered_at?: string | null
  closed_at?: string | null
}

export type SupportMetrics = {
  total_requests: number
  faq_share: number
  rag_share: number
  operator_share: number
  average_confidence: number
  empty_sources_share: number
  feedback_count: number
  average_rating: number
}

export type ReindexResult = {
  message: string
  reindexed_sources: number
  reindexed_docs: number
  orphan_vectors_removed: number
  full_rebuild: boolean
}

export type ListResponse<T> = { data: T[]; count: number }

const authHeader = () => ({
  Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
})

const jsonHeaders = () => ({
  "Content-Type": "application/json",
  ...authHeader(),
})

/** Ошибка API со статусом — нужна, чтобы различать 409 (конфликт) и остальные сбои. */
export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

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
      // тело может быть пустым
    }
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
    )
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

const query = (
  params: Record<string, string | number | boolean | undefined>,
) => {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value))
  })
  const asString = search.toString()
  return asString ? `?${asString}` : ""
}

/* ------------------------------- пользователь ------------------------------ */

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
  request<ListResponse<SupportHistoryEntry>>(
    `/api/v1/support/history${query({ session_id: sessionId })}`,
    { method: "GET", headers: authHeader() },
  )

export const submitSupportFeedback = (payload: {
  request_id: string
  rating: number
  comment?: string
}) =>
  request<SupportFeedback>("/api/v1/support/feedback", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })

/* ---------------------------------- FAQ ----------------------------------- */

export const getFaqEntries = () =>
  request<ListResponse<FaqEntry>>("/api/v1/admin/faq", {
    method: "GET",
    headers: authHeader(),
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
    headers: authHeader(),
  })

/* -------------------------------- источники -------------------------------- */

export const getKnowledgeSources = () =>
  request<ListResponse<KnowledgeSource>>("/api/v1/admin/sources", {
    method: "GET",
    headers: authHeader(),
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
    headers: authHeader(),
    body: formData,
  })
}

export const updateKnowledgeSource = (
  sourceId: string,
  payload: {
    title?: string
    category_id?: string | null
    is_active?: boolean
    tags?: string[]
  },
) =>
  request<KnowledgeSource>(`/api/v1/admin/sources/${sourceId}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })

export const deleteKnowledgeSource = (sourceId: string) =>
  request<{ message: string }>(`/api/v1/admin/sources/${sourceId}`, {
    method: "DELETE",
    headers: authHeader(),
  })

export const deactivateKnowledgeSource = (sourceId: string) =>
  request<KnowledgeSource>(`/api/v1/admin/sources/${sourceId}/deactivate`, {
    method: "POST",
    headers: authHeader(),
  })

export const getSourceArchive = (sourceId: string) =>
  request<ListResponse<KnowledgeArchiveEntry>>(
    `/api/v1/admin/sources/${sourceId}/archive`,
    { method: "GET", headers: authHeader() },
  )

export const reindexKnowledgeSources = (options?: {
  sourceIds?: string[]
  docIds?: string[]
  fullRebuild?: boolean
  purgeOrphans?: boolean
}) =>
  request<ReindexResult>("/api/v1/admin/sources/reindex", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      source_ids: options?.sourceIds,
      doc_ids: options?.docIds,
      full_rebuild: options?.fullRebuild ?? false,
      purge_orphans: options?.purgeOrphans ?? true,
    }),
  })

/* -------------------------------- документы -------------------------------- */

export const getKnowledgeDocs = () =>
  request<ListResponse<KnowledgeDoc>>("/api/v1/admin/docs", {
    method: "GET",
    headers: authHeader(),
  })

export const createKnowledgeDoc = (payload: {
  title: string
  url: string
  tags?: string[]
}) =>
  request<KnowledgeDoc>("/api/v1/admin/docs", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })

export const updateKnowledgeDoc = (
  docId: string,
  payload: { title?: string; url?: string; tags?: string[] },
) =>
  request<KnowledgeDoc>(`/api/v1/admin/docs/${docId}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })

export const deleteKnowledgeDoc = (docId: string) =>
  request<{ message: string }>(`/api/v1/admin/docs/${docId}`, {
    method: "DELETE",
    headers: authHeader(),
  })

/** Переиндексация только корпуса документов (источники не затрагиваются). */
export const reindexKnowledgeDocs = (options?: {
  docIds?: string[]
  purgeOrphans?: boolean
}) =>
  request<ReindexResult>("/api/v1/admin/docs/reindex", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      doc_ids: options?.docIds,
      purge_orphans: options?.purgeOrphans ?? true,
    }),
  })

/* ------------------------------- таксономия -------------------------------- */

export const getCategories = () =>
  request<ListResponse<KnowledgeCategory>>("/api/v1/admin/categories", {
    method: "GET",
    headers: authHeader(),
  })

export const createCategory = (name: string) =>
  request<KnowledgeCategory>("/api/v1/admin/categories", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ name }),
  })

export const updateCategory = (categoryId: string, name: string) =>
  request<KnowledgeCategory>(`/api/v1/admin/categories/${categoryId}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify({ name }),
  })

export const deleteCategory = (categoryId: string) =>
  request<{ message: string }>(`/api/v1/admin/categories/${categoryId}`, {
    method: "DELETE",
    headers: authHeader(),
  })

export const getTags = () =>
  request<ListResponse<KnowledgeTag>>("/api/v1/admin/tags", {
    method: "GET",
    headers: authHeader(),
  })

export const createTag = (name: string) =>
  request<KnowledgeTag>("/api/v1/admin/tags", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ name }),
  })

export const deleteTag = (tagId: string) =>
  request<{ message: string }>(`/api/v1/admin/tags/${tagId}`, {
    method: "DELETE",
    headers: authHeader(),
  })

/* ---------------------------------- поиск ---------------------------------- */

export const searchKnowledge = (payload: {
  question: string
  owner_types?: ("source" | "doc")[]
  category_ids?: string[]
  tag_ids?: string[]
  limit?: number
}) =>
  request<ListResponse<KnowledgeSearchHit>>("/api/v1/admin/knowledge/search", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })

/* -------------------------- запросы, тикеты, метрики ------------------------ */

export const getActiveRequests = (params?: { skip?: number; limit?: number }) =>
  request<ListResponse<ActiveRequest>>(
    `/api/v1/admin/requests/active${query({ ...params })}`,
    { method: "GET", headers: authHeader() },
  )

export const getJournalRequests = (params?: {
  status?: string
  skip?: number
  limit?: number
}) =>
  request<ListResponse<JournalRequest>>(
    `/api/v1/admin/requests/journal${query({ ...params })}`,
    { method: "GET", headers: authHeader() },
  )

export const getOperatorQueue = () =>
  request<ListResponse<SupportTicket>>("/api/v1/admin/operator-queue", {
    method: "GET",
    headers: authHeader(),
  })

export const assignTicket = (ticketId: string, assignedTo?: string | null) =>
  request<SupportTicket>(`/api/v1/admin/tickets/${ticketId}/assign`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ assigned_to: assignedTo ?? null }),
  })

export const resolveTicket = (ticketId: string, resolution: string) =>
  request<SupportTicket>(`/api/v1/admin/tickets/${ticketId}/resolve`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ resolution }),
  })

export const reopenTicket = (ticketId: string, reason?: string) =>
  request<SupportTicket>(`/api/v1/admin/tickets/${ticketId}/reopen`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ reason: reason || null }),
  })

export const getMyQueue = () =>
  request<ListResponse<MyQueueEntry>>("/api/v1/support/my-queue", {
    method: "GET",
    headers: authHeader(),
  })

export const getSupportMetrics = () =>
  request<SupportMetrics>("/api/v1/admin/metrics", {
    method: "GET",
    headers: authHeader(),
  })
