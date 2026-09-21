export const DEFAULT_ENDPOINT = "http://127.0.0.1:8765/mcp";

export interface PluginSettings {
  endpoint: string;
}

export interface SearchFilters {
  type?: string;
  tags?: string[];
  path_prefix?: string;
  include_sources?: boolean;
}

export interface SearchHit {
  path: string;
  title?: string;
  score?: number;
  excerpt?: string;
  [key: string]: unknown;
}

export interface SearchResult {
  results: SearchHit[];
  total?: number;
  [key: string]: unknown;
}

export interface MemoryPage {
  path: string;
  content: string;
  revision?: string;
  [key: string]: unknown;
}

export interface ReflectResult {
  query?: string;
  reflection?: string;
  sources?: Array<{ path: string }>;
  error?: string;
  message?: string;
}
