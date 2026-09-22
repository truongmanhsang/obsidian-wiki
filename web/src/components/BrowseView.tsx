import { useEffect, useMemo, useState } from 'react'
import { FileText, Search } from 'lucide-react'
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
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listPages().then(value => { setPages(value.pages); setStats(value.stats) })
      .catch(reason => setError(reason instanceof Error ? reason.message : 'Library is unavailable'))
      .finally(() => setLoading(false))
  }, [])

  const types = useMemo(() => ['all', ...Object.entries(stats).filter(([, count]) => count > 0).map(([type]) => type)], [stats])
  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return pages.filter(page => filter === 'all' || page.type === filter)
      .filter(page => !normalized || page.title.toLowerCase().includes(normalized) || page.path.toLowerCase().includes(normalized))
      .sort((a, b) => String(b.updated).localeCompare(String(a.updated)))
  }, [filter, pages, query])
  const total = Object.values(stats).reduce((sum, value) => sum + Number(value || 0), 0) || pages.length

  return (
    <div className="view-stack">
      <div className="page-header page-header-row">
        <div><div className="eyebrow">Curated knowledge</div><h1>Library</h1>
          <p>Browse the canonical pages agents use for durable context and grounded answers.</p></div>
        <div className="header-stat"><strong>{total}</strong><span>pages</span></div>
      </div>

      {loading && <LoadingState label="Loading the library…" />}
      {error && <ErrorBanner message={error} onRetry={() => window.location.reload()} />}

      {!loading && !error && <>
        <div className="library-toolbar">
          <label className="inline-search"><Search size={14} />
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Filter pages…" aria-label="Filter library" />
          </label>
          <div className="filter-scroll" aria-label="Filter catalog">
            {types.map(type => <button type="button" className={'filter-chip ' + (filter === type ? 'active' : '')}
              onClick={() => setFilter(type)} key={type}>{type}{type !== 'all' && <span>{stats[type] ?? 0}</span>}</button>)}
          </div>
        </div>

        <section className="panel library-panel">
          <div className="library-list-head"><span>Name</span><span>Type</span><span>Updated</span></div>
          <div className="library-list">
            {visible.map(page => <button className="library-row" key={page.path} onClick={() => onOpenPage(page.path)}>
              <span className="library-name"><span className="row-icon"><FileText size={14} /></span>
                <span><strong>{page.title}</strong><small>{page.path}</small></span></span>
              <span><span className="type-pill">{page.type}</span></span>
              <span className="library-date">{formatDate(page.updated)}</span>
            </button>)}
          </div>
        </section>

        {!visible.length && <EmptyState title="No pages in this view" message="Try another type or clear the library filter." />}
      </>}
    </div>
  )
}
