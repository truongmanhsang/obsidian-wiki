import {
  ApiError,
  type GraphResponse,
  type HealthResponse,
  type IngestJob,
  type IngestStatus,
  type LogResponse,
  type MemoryPage,
  type MemoryPageDetail,
  type PageListResponse,
  type ReflectResponse,
  type SearchResponse,
} from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new ApiError(payload.message ?? `Request failed (${response.status})`, response.status)
  }
  return payload as T
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health')
}

export function searchMemory(params: {
  query: string
  limit?: number
  type?: string
  tag?: string
  precise?: boolean
}): Promise<SearchResponse> {
  const search = new URLSearchParams({ q: params.query })
  if (params.limit) search.set('limit', String(params.limit))
  if (params.type) search.set('type', params.type)
  if (params.tag) search.set('tag', params.tag)
  if (params.precise !== undefined) search.set('precise', String(params.precise))
  return request<SearchResponse>(`/api/search?${search.toString()}`)
}

export function listPages(params: {
  limit?: number
  offset?: number
  type?: string
  query?: string
} = {}): Promise<PageListResponse> {
  const search = new URLSearchParams()
  search.set('limit', String(params.limit ?? 25))
  search.set('offset', String(params.offset ?? 0))
  if (params.type && params.type !== 'all') search.set('type', params.type)
  if (params.query?.trim()) search.set('q', params.query.trim())
  return request<PageListResponse>(`/api/pages?${search.toString()}`)
}

export function getGraph(): Promise<GraphResponse> {
  return request<GraphResponse>('/api/graph')
}

export function resolveWikiLink(target: string, fromPath: string): Promise<{ path: string; fragment: string }> {
  const search = new URLSearchParams({ target, from: fromPath })
  return request(`/api/resolve?${search.toString()}`)
}

export function readPage(path: string): Promise<MemoryPageDetail> {
  return request(`/api/pages/${path.split('/').map(encodeURIComponent).join('/')}`)
}

export function reflectMemory(query: string, limit = 8): Promise<ReflectResponse> {
  return request<ReflectResponse>('/api/reflect', {
    method: 'POST',
    body: JSON.stringify({ query, limit }),
  })
}

export function getLogs(limit = 100): Promise<LogResponse> {
  return request<LogResponse>(`/api/logs?limit=${limit}`)
}

export function getIngestStatus(jobId?: string): Promise<IngestStatus | IngestJob> {
  const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''
  return request<IngestStatus | IngestJob>(`/api/ingest/status${suffix}`)
}
