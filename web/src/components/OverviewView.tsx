import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowRight,
  BookOpenText,
  CheckCircle2,
  Clock3,
  FileStack,
  RefreshCw,
  Search,
  Sparkles,
} from 'lucide-react'
import { getHealth, getIngestStatus, getLogs, listPages } from '../api'
import { logLines } from '../logFormat'
import type { IngestJob, MemoryPage } from '../types'
import type { View } from '../App'
import { ErrorBanner } from './ErrorBanner'

function timeAgo(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

function statusTone(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'running'
  return 'neutral'
}

export function OverviewView({
  onNavigate,
  onOpenPage,
}: {
  onNavigate: (view: Exclude<View, 'page'>) => void
  onOpenPage: (path: string) => void
}) {
  const [pages, setPages] = useState<MemoryPage[]>([])
  const [stats, setStats] = useState<Record<string, number>>({})
  const [jobs, setJobs] = useState<IngestJob[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [online, setOnline] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [catalog, health, ingest, logResult] = await Promise.all([
        listPages(),
        getHealth(),
        getIngestStatus(),
        getLogs(12),
      ])
      setPages(catalog.pages ?? [])
      setStats(catalog.stats ?? {})
      setOnline(Boolean(health?.ok))
      setJobs('jobs' in ingest ? (ingest.jobs ?? []) : [ingest])
      setLogs(logLines(logResult))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Workspace status is unavailable')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const pageCount = useMemo(
    () => Object.values(stats).reduce((sum, count) => sum + Number(count || 0), 0) || pages.length,
    [pages.length, stats],
  )
  const typeCount = useMemo(() => Object.values(stats).filter(value => value > 0).length, [stats])
  const sortedPages = useMemo(
    () => [...pages].sort((a, b) => String(b.updated).localeCompare(String(a.updated))).slice(0, 5),
    [pages],
  )
  const recentJobs = useMemo(
    () => [...jobs].sort((a, b) => String(b.submitted_at ?? '').localeCompare(String(a.submitted_at ?? ''))).slice(0, 5),
    [jobs],
  )
  const activeJob = jobs.find(job => job.status === 'running' || job.status === 'queued')

  return (
    <div className="view-stack">
      <div className="page-header page-header-row">
        <div>
          <div className="eyebrow">System workspace</div>
          <h1>Overview</h1>
          <p>Search health, knowledge coverage, and ingestion activity in one place.</p>
        </div>
        <button className="secondary-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} />
          Refresh
        </button>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="metric-grid">
        <div className="metric-card">
          <span className="metric-icon"><FileStack size={17} /></span>
          <div className="metric-label">Curated pages</div>
          <div className="metric-value">{pageCount}</div>
          <div className="metric-foot">{typeCount} active knowledge types</div>
        </div>
        <div className="metric-card">
          <span className="metric-icon"><Activity size={17} /></span>
          <div className="metric-label">Memory service</div>
          <div className="metric-value metric-text">{online ? 'Operational' : 'Checking'}</div>
          <div className="metric-foot"><span className={`inline-dot ${online ? 'ok' : ''}`} /> local API</div>
        </div>
        <div className="metric-card">
          <span className="metric-icon"><Clock3 size={17} /></span>
          <div className="metric-label">Ingest pipeline</div>
          <div className="metric-value metric-text">{activeJob ? activeJob.status : 'Idle'}</div>
          <div className="metric-foot">{jobs.length} jobs retained</div>
        </div>
        <div className="metric-card">
          <span className="metric-icon"><CheckCircle2 size={17} /></span>
          <div className="metric-label">Completed jobs</div>
          <div className="metric-value">{jobs.filter(job => job.status === 'completed').length}</div>
          <div className="metric-foot">{jobs.filter(job => job.status === 'failed').length} failed</div>
        </div>
      </div>

      <div className="overview-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>Recently updated</h2>
              <p>Latest curated knowledge in the vault</p>
            </div>
            <button className="text-button" onClick={() => onNavigate('library')}>View library <ArrowRight size={13} /></button>
          </div>
          <div className="compact-list">
            {sortedPages.map(page => (
              <button className="compact-row" key={page.path} onClick={() => onOpenPage(page.path)}>
                <span className="row-icon"><BookOpenText size={15} /></span>
                <span className="row-main">
                  <strong>{page.title}</strong>
                  <span>{page.path}</span>
                </span>
                <span className="row-meta">{page.updated || '—'}</span>
              </button>
            ))}
            {!sortedPages.length && <div className="panel-empty">No curated pages yet.</div>}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>Ingest queue</h2>
              <p>Recent session extraction jobs</p>
            </div>
            <button className="text-button" onClick={() => onNavigate('operations')}>Operations <ArrowRight size={13} /></button>
          </div>
          <div className="compact-list">
            {recentJobs.map(job => (
              <div className="compact-row static-row" key={job.job_id}>
                <span className={`job-dot ${statusTone(job.status)}`} />
                <span className="row-main">
                  <strong>{job.session_id ? `Session ${job.session_id.slice(0, 10)}` : job.job_id}</strong>
                  <span>{job.job_id}</span>
                </span>
                <span className="row-meta">
                  <span className={`status-badge ${statusTone(job.status)}`}>{job.status}</span>
                  <small>{timeAgo(job.submitted_at)}</small>
                </span>
              </div>
            ))}
            {!recentJobs.length && <div className="panel-empty">No ingest jobs recorded.</div>}
          </div>
        </section>
      </div>

      <div className="overview-grid lower-grid">
        <section className="panel activity-panel">
          <div className="panel-header">
            <div>
              <h2>Recent activity</h2>
              <p>Vault operation log</p>
            </div>
          </div>
          <div className="log-preview">
            {logs.slice(0, 7).map((line, index) => <code key={index}>{line}</code>)}
            {!logs.length && <div className="panel-empty">No recent operations.</div>}
          </div>
        </section>

        <section className="panel quick-panel">
          <div className="panel-header">
            <div>
              <h2>Quick actions</h2>
              <p>Jump into the primary workflows</p>
            </div>
          </div>
          <div className="quick-actions">
            <button onClick={() => onNavigate('search')}><Search size={16} /><span><strong>Search memory</strong><small>Find exact facts and decisions</small></span><ArrowRight size={14} /></button>
            <button onClick={() => onNavigate('reflect')}><Sparkles size={16} /><span><strong>Reflect</strong><small>Synthesize across related pages</small></span><ArrowRight size={14} /></button>
            <button onClick={() => onNavigate('operations')}><Activity size={16} /><span><strong>Inspect pipeline</strong><small>Review jobs and operation logs</small></span><ArrowRight size={14} /></button>
          </div>
        </section>
      </div>
    </div>
  )
}
