import { useEffect, useMemo, useState } from 'react'
import { Compass, FileText } from 'lucide-react'
import { listPages } from '../api'
import type { MemoryPage } from '../types'
import { EmptyState } from './EmptyState'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'

export function BrowseView({ onOpenPage }: { onOpenPage: (path: string) => void }) {
  const [pages, setPages] = useState<MemoryPage[]>([])
  const [stats, setStats] = useState<Record<string, number>>({})
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { listPages().then(value => { setPages(value.pages); setStats(value.stats) }).catch(reason => setError(reason instanceof Error ? reason.message : 'Browse is unavailable')).finally(() => setLoading(false)) }, [])
  const types = useMemo(() => ['all', ...Array.from(new Set(pages.map(page => page.type)))], [pages])
  const visible = filter === 'all' ? pages : pages.filter(page => page.type === filter)
  return <div className="view-stack"><div className="view-heading"><div><span className="hero-kicker">A living catalog</span><h1>Browse the vault.</h1><p>Every curated page, gathered in one quiet place.</p></div><div className="catalog-stat"><strong>{stats.pages ?? pages.length}</strong><span>pages</span></div></div>{loading && <LoadingState label="Gathering the vault…" />}{error && <ErrorBanner message={error} onRetry={() => window.location.reload()} />}{!loading && !error && <><div className="filter-row" aria-label="Filter catalog">{types.map(type => <button type="button" className={`filter-chip ${filter === type ? 'active' : ''}`} onClick={() => setFilter(type)} key={type}>{type}</button>)}</div><div className="catalog-grid">{visible.map(page => <button className="catalog-card" key={page.path} onClick={() => onOpenPage(page.path)} aria-label={page.title}><span className="catalog-card-icon"><FileText size={17} /></span><span><strong>{page.title}</strong><small>{page.path}</small></span></button>)}</div>{visible.length === 0 && <EmptyState title="No pages in this view" message="Try a different type filter." />}</>}</div>
}
