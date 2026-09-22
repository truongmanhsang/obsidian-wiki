import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  CheckCircle2,
  CircleDashed,
  Clock3,
  RefreshCw,
  TerminalSquare,
  XCircle,
} from 'lucide-react'
import { getIngestStatus, getLogs } from '../api'
import { logLines } from '../logFormat'
import type { IngestJob } from '../types'
import { ErrorBanner } from './ErrorBanner'

function tone(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'running'
  return 'neutral'
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 size={15} />
  if (status === 'failed') return <XCircle size={15} />
  if (status === 'running') return <Activity size={15} />
  if (status === 'queued') return <Clock3 size={15} />
  return <CircleDashed size={15} />
}

function formatTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function OperationsView() {
  const [jobs, setJobs] = useState<IngestJob[]>([])
  const [running, setRunning] = useState<string | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [status, logResult] = await Promise.all([getIngestStatus(), getLogs(150)])
      if ('jobs' in status) {
        setJobs(status.jobs)
        setRunning(status.running)
      } else {
        setJobs([status])
      }
      setLogs(logLines(logResult))
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Operations data is unavailable')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(timer)
  }, [load])

  const orderedJobs = useMemo(
    () => [...jobs].sort((a, b) => String(b.submitted_at ?? '').localeCompare(String(a.submitted_at ?? ''))),
    [jobs],
  )

  return (
    <div className="view-stack">
      <div className="page-header page-header-row">
        <div>
          <div className="eyebrow">Runtime visibility</div>
          <h1>Operations</h1>
          <p>Monitor ingestion, failures, and vault activity without leaving the memory workspace.</p>
        </div>
        <button className="secondary-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="ops-summary">
        <div><span className="inline-dot ok" /><strong>Memory API</strong><small>available</small></div>
        <div><span className={`inline-dot ${running ? 'busy' : 'ok'}`} /><strong>Ingest worker</strong><small>{running ? 'active' : 'idle'}</small></div>
        <div><TerminalSquare size={14} /><strong>Log stream</strong><small>{logs.length} recent lines</small></div>
      </div>

      <section className="panel ops-panel">
        <div className="panel-header">
          <div>
            <h2>Ingest jobs</h2>
            <p>Centralized session capture and durable knowledge extraction</p>
          </div>
          <span className="muted-caption">Auto-refresh · 5s</span>
        </div>

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Job</th>
                <th>Session</th>
                <th>Submitted</th>
                <th>Finished</th>
              </tr>
            </thead>
            <tbody>
              {orderedJobs.map(job => (
                <tr key={job.job_id}>
                  <td><span className={`status-badge with-icon ${tone(job.status)}`}><StatusIcon status={job.status} />{job.status}</span></td>
                  <td><code>{job.job_id}</code>{job.error && <span className="cell-error">{job.error}</span>}</td>
                  <td><span className="mono-muted">{job.session_id ?? 'all / latest'}</span></td>
                  <td>{formatTime(job.submitted_at)}</td>
                  <td>{formatTime(job.finished_at)}</td>
                </tr>
              ))}
              {!orderedJobs.length && (
                <tr><td colSpan={5}><div className="table-empty">No ingest jobs have been recorded.</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel ops-panel log-panel">
        <div className="panel-header">
          <div>
            <h2>Vault log</h2>
            <p>Recent write, append, delete, and indexing activity</p>
          </div>
          <TerminalSquare size={16} className="panel-icon" />
        </div>
        <div className="log-console" role="log" aria-label="Vault operation log">
          {logs.map((line, index) => (
            <div className="log-line" key={index}>
              <span className="log-index">{String(logs.length - index).padStart(3, '0')}</span>
              <code>{line}</code>
            </div>
          ))}
          {!logs.length && <div className="console-empty">No log entries available.</div>}
        </div>
      </section>
    </div>
  )
}
