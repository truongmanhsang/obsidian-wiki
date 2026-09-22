import { useRef, useState } from 'react'
import { ArrowRight, Search, SlidersHorizontal, Sparkles } from 'lucide-react'
import { searchMemory } from '../api'
import type { MemoryResult } from '../types'
import { EmptyState } from './EmptyState'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'
import { ResultCard } from './ResultCard'

const types = ['all', 'entity', 'concept', 'decision', 'person', 'environment', 'answer', 'preference']

export function SearchView({ inputRef, onOpenPage, onReflect }: {
  inputRef: React.RefObject<HTMLInputElement | null>
  onOpenPage: (path: string) => void
  onReflect: (query: string) => void
}) {
  const [query, setQuery] = useState('')
  const [type, setType] = useState('all')
  const [precise, setPrecise] = useState(true)
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
    setLoading(true)
    setError(null)
    setSubmitted(value)
    try {
      const response = await searchMemory({ query: value, type: type === 'all' ? undefined : type, precise, limit: 20 })
      setResults(response.results)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Search is unavailable')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="view-stack">
      <div className="page-header">
        <div className="eyebrow">Knowledge retrieval</div>
        <h1>Search</h1>
        <p>Find exact facts, decisions, people, and reusable knowledge across the curated vault.</p>
      </div>

      <form className="search-composer" onSubmit={submit}>
        <Search size={18} className="search-composer-icon" />
        <input ref={actualRef} type="search" value={query} onChange={event => setQuery(event.target.value)}
          placeholder="Search memory…" aria-label="Search memory" />
        <button className="search-submit" type="submit" disabled={!query.trim() || loading}>
          Search <ArrowRight size={14} />
        </button>
      </form>

      <div className="search-toolbar">
        <div className="filter-scroll" aria-label="Filter by type">
          {types.map(option => (
            <button type="button" key={option} className={'filter-chip ' + (type === option ? 'active' : '')}
              onClick={() => setType(option)}>{option}</button>
          ))}
        </div>
        <button type="button" className={'mode-toggle ' + (precise ? 'active' : '')}
          onClick={() => setPrecise(value => !value)}
          title="Precise search prioritizes stricter lexical matches">
          <SlidersHorizontal size={13} />{precise ? 'Precise' : 'Semantic'}
        </button>
      </div>

      {loading && <LoadingState label="Searching the vault…" />}
      {error && <ErrorBanner message={error} onRetry={() => void submit()} />}

      {!loading && !error && submitted && (
        <section className="results-section" aria-live="polite">
          <div className="section-bar">
            <div><strong>{results.length} results</strong><span>for “{submitted}”</span></div>
            <button className="text-button" onClick={() => onReflect(submitted)}><Sparkles size={13} /> Reflect on this</button>
          </div>
          <div className="results-stack">
            {results.length ? results.map(result => <ResultCard key={result.path} result={result} onOpen={onOpenPage} />)
              : <EmptyState title="No matching memory" message="Try a broader phrase, switch to semantic mode, or reflect across related pages." />}
          </div>
        </section>
      )}

      {!submitted && (
        <section className="search-guide panel">
          <div className="panel-header"><div><h2>Search patterns</h2><p>Good queries anchor on a fact, decision, system, or project.</p></div></div>
          <div className="query-examples">
            {['deployment retry policy', 'why did we choose semantic search', 'Hermes memory configuration', 'recent experiment conclusion'].map(example => (
              <button key={example} onClick={() => { setQuery(example); actualRef.current?.focus() }}><Search size={13} /> {example}</button>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
