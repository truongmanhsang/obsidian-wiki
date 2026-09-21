import { ApiError, type MemoryPage, type MemoryPageDetail, type MemoryStats, type ReflectResponse, type SearchResponse } from './types'

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

export function searchMemory(params: { query: string; limit?: number; type?: string; tag?: string }): Promise<SearchResponse> {
  const search = new URLSearchParams({ q: params.query })
  if (params.limit) search.set('limit', String(params.limit))
  if (params.type) search.set('type', params.type)
  if (params.tag) search.set('tag', params.tag)
  return request<SearchResponse>(`/api/search?${search.toString()}`)
}

export function listPages(limit = 200): Promise<{ stats: MemoryStats; pages: MemoryPage[] }> {
  return request(`/api/pages?limit=${limit}`)
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
