import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, FileText, Search } from 'lucide-react'
import { listPages } from '../api'
import type { MemoryPage } from '../types'
import { EmptyState } from './EmptyState'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'

function formatDate(value: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: '2-digit' }).format(date)
}

export function BrowseView({ onOpenPage }: { onOpenPage: (path: string) => void }) {
  const [pages, setPages] = useState<MemoryPage[]>([])
  const [stats, setStats] = useState<Record<string, number>>({})
  const [resultTotal, setResultTotal] = useState(0)
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    listPages({
      limit: pageSize,
      offset: (page - 1) * pageSize,
      type: filter,
      query,
    }).then(value => {
      if (!active) return
      setPages(value.pages)
      setStats(value.stats)
      setResultTotal(value.total)
      const lastPage = Math.max(1, Math.ceil(value.total / pageSize))
      if (page > lastPage) setPage(lastPage)
    }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : 'Library is unavailable')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [filter, page, pageSize, query])

  const types = useMemo(() => ['all', ...Object.entries(stats).filter(([, count]) => count > 0).map(([type]) => type)], [stats])
  const total = Object.values(stats).reduce((sum, value) => sum + Number(value || 0), 0)
  const pageCount = Math.max(1, Math.ceil(resultTotal / pageSize))
  const pageStart = (page - 1) * pageSize
  const rangeStart = resultTotal ? pageStart + 1 : 0
  const rangeEnd = Math.min(pageStart + pages.length, resultTotal)

  const selectFilter = (type: string) => {
    setPage(1)
    setFilter(type)
  }

  const updateQuery = (value: string) => {
    setPage(1)
    setQuery(value)
  }

  const updatePageSize = (value: number) => {
    setPage(1)
    setPageSize(value)
  }

  return (
    <div className="view-stack">
      <div className="page-header page-header-row">
        <div><div className="eyebrow">Curated knowledge</div><h1>Library</h1>
          <p>Browse the canonical pages agents use for durable context and grounded answers.</p></div>
        <div className="header-stat"><strong>{total}</strong><span>pages</span></div>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => window.location.reload()} />}

      <div className="library-toolbar">
        <label className="inline-search"><Search size={14} />
          <input value={query} onChange={event => updateQuery(event.target.value)} placeholder="Filter pages…" aria-label="Filter library" />
        </label>
        <div className="filter-scroll" aria-label="Filter catalog">
          {types.map(type => <button type="button" className={'filter-chip ' + (filter === type ? 'active' : '')}
            onClick={() => selectFilter(type)} key={type}>{type}{type !== 'all' && <span>{stats[type] ?? 0}</span>}</button>)}
        </div>
      </div>

      <section className="panel library-panel" aria-busy={loading}>
        <div className="library-list-head"><span>Name</span><span>Type</span><span>Updated</span></div>
        {loading ? <LoadingState label="Loading the library…" /> : <div className="library-list">
          {pages.map(item => <button className="library-row" key={item.path} onClick={() => onOpenPage(item.path)}>
            <span className="library-name"><span className="row-icon"><FileText size={14} /></span>
              <span><strong>{item.title}</strong><small>{item.path}</small></span></span>
            <span><span className="type-pill">{item.type}</span></span>
            <span className="library-date">{formatDate(item.updated)}</span>
          </button>)}
        </div>}
        {!loading && resultTotal > 0 && <nav className="library-pagination" aria-label="Library pagination">
          <div className="pagination-summary">
            <span aria-live="polite">Showing <strong>{rangeStart}–{rangeEnd}</strong> of <strong>{resultTotal}</strong></span>
            <label>Rows
              <select value={pageSize} onChange={event => updatePageSize(Number(event.target.value))} aria-label="Rows per page">
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </label>
          </div>
          <div className="pagination-controls">
            <button type="button" className="pagination-button icon-only" onClick={() => setPage(value => Math.max(1, value - 1))} disabled={page === 1} aria-label="Previous library page">
              <ChevronLeft size={15} />
            </button>
            <span className="pagination-page" aria-label={`Page ${page} of ${pageCount}`}>Page <strong>{page}</strong> of <strong>{pageCount}</strong></span>
            <button type="button" className="pagination-button icon-only" onClick={() => setPage(value => Math.min(pageCount, value + 1))} disabled={page === pageCount} aria-label="Next library page">
              <ChevronRight size={15} />
            </button>
          </div>
        </nav>}
      </section>

      {!loading && !error && resultTotal === 0 && <EmptyState title="No pages in this view" message="Try another type or clear the library filter." />}
    </div>
  )
}
