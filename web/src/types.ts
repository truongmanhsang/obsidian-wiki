export type PageType = 'entity' | 'person' | 'decision' | 'environment' | 'concept' | 'answer' | 'preference' | 'source' | string

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

export type PageListResponse = {
  stats: MemoryStats
  pages: MemoryPage[]
  total: number
  offset: number
  limit: number
}

export type GraphNode = {
  id: string
  path: string
  title: string
  type: PageType
  updated: string
  tags: string[]
}

export type GraphLink = {
  source: string
  target: string
  weight: number
}

export type GraphResponse = {
  nodes: GraphNode[]
  links: GraphLink[]
  count: { nodes: number; links: number }
}

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

export type HealthResponse = {
  ok: boolean
  service: string
  pages: number
}

export type IngestJob = {
  job_id: string
  request_id?: string | null
  session_id?: string | null
  status: 'queued' | 'running' | 'completed' | 'failed' | string
  submitted_at?: string
  started_at?: string
  finished_at?: string
  resubmitted_at?: string
  capture_output?: string
  extract_output?: string
  error?: string
}

export type IngestStatus = {
  running: string | null
  jobs: IngestJob[]
}

export type LogEntry = {
  date: string
  kind: string
  message: string
  is_auto: boolean
  created_at?: string
}

export type LogResponse = {
  log_tail: string
  entries?: LogEntry[]
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
