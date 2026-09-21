import { useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { searchMemory } from '../api'
import type { MemoryResult } from '../types'
import { EmptyState } from './EmptyState'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'
import { ResultCard } from './ResultCard'

const types = ['all', 'person', 'concept', 'decision', 'entity']

export function SearchView({ inputRef, onOpenPage, onReflect }: { inputRef: React.RefObject<HTMLInputElement | null>; onOpenPage: (path: string) => void; onReflect: (query: string) => void }) {
  const [query, setQuery] = useState('')
  const [type, setType] = useState('all')
  const [results, setResults] = useState<MemoryResult[]>([])
  const [submitted, setSubmitted] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputFallback = useRef<HTMLInputElement>(null)
  const actualRef = inputRef ?? inputFallback

  async function submit(event?: React.FormEvent) {
    event?.preventDefault()
    const value = query.trim()
    if (!value) return
    setLoading(true); setError(null); setSubmitted(value)
    try {
      const response = await searchMemory({ query: value, type: type === 'all' ? undefined : type })
      setResults(response.results)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Search is unavailable')
    } finally { setLoading(false) }
  }

  return <>
    <div className="hero-copy"><span className="hero-kicker">Quietly find what matters</span><h1>Search your memory.</h1><p>Explore the ideas, decisions, and people that make your work legible over time.</p></div>
    <form className="search-bar-wrap" onSubmit={submit}>
      <Search size={20} className="search-icon" />
      <input ref={actualRef} className="search-input" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search decisions, people, concepts…" aria-label="Search memory" />
      <kbd className="search-shortcut">⌘ K</kbd>
    </form>
    <div className="filter-row" aria-label="Filter by type">{types.map(option => <button type="button" key={option} className={`filter-chip ${type === option ? 'active' : ''}`} onClick={() => setType(option)}>{option}</button>)}</div>
    {loading && <LoadingState label="Searching your memory…" />}
    {error && <ErrorBanner message={error} onRetry={() => submit()} />}
    {!loading && !error && submitted && <div className="results-stack" aria-live="polite"><div className="results-heading"><span>{results.length} {results.length === 1 ? 'memory' : 'memories'} for <strong>“{submitted}”</strong></span><button className="text-action" onClick={() => onReflect(submitted)}>Reflect on this →</button></div>{results.length ? results.map(result => <ResultCard key={result.path} result={result} onOpen={onOpenPage} />) : <EmptyState title="Nothing surfaced yet" message="Try a broader phrase or ask Reflect to reason over a different question." />}</div>}
    {!submitted && <div className="search-starters"><div className="starter-note"><span className="starter-note-dot" /><span>Tip: search by a feeling, decision, person, or project name.</span></div></div>}
  </>
}
