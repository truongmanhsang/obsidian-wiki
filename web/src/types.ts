export type PageType = 'entity' | 'person' | 'decision' | 'environment' | 'concept' | 'answer' | 'preference' | string

export type MemoryResult = {
  path: string
  title: string
  type: PageType
  updated: string
  snippet?: string
  score?: number
  match?: string
  tags?: string[]
}

export type MemoryPage = {
  path: string
  title: string
  type: PageType
  updated: string
}

export type MemoryStats = Record<string, number>

export type MemoryPageDetail = {
  path: string
  content: string
  truncated: boolean
  revision: string
}

export type SearchResponse = {
  results: MemoryResult[]
  count: number
}

export type ReflectResponse = {
  query: string
  reflection: string
  sources: Array<{ path: string }>
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
