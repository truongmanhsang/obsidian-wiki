import { useEffect, useState } from 'react'
import { ArrowLeft, FileText } from 'lucide-react'
import { readPage } from '../api'
import type { MemoryPageDetail } from '../types'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'

export function PageView({ path, onBack }: { path: string; onBack: () => void }) {
  const [page, setPage] = useState<MemoryPageDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { let active = true; setPage(null); setError(null); readPage(path).then(value => active && setPage(value)).catch(reason => active && setError(reason instanceof Error ? reason.message : 'Page unavailable')); return () => { active = false } }, [path])
  if (error) return <><button className="back-button" onClick={onBack}><ArrowLeft size={16} /> Back</button><ErrorBanner message={error} /></>
  if (!page) return <LoadingState label="Opening page…" />
  const lines = page.content.split('\n')
  const title = lines.find(line => line.startsWith('# '))?.slice(2) ?? page.path.split('/').pop()?.replace('.md', '') ?? page.path
  return <article className="page-article">
    <button className="back-button" onClick={onBack}><ArrowLeft size={16} /> Back</button>
    <div className="page-heading"><span className="page-icon"><FileText size={18} /></span><div><span className="page-path">{page.path}</span><h1>{title}</h1></div></div>
    <div className="page-content">{lines.filter(line => !line.startsWith('---') && !line.startsWith('type:') && !line.startsWith('updated:') && !line.startsWith('tags:') && !line.startsWith('aliases:')).map((line, index) => line.startsWith('#') ? <h2 key={index}>{line.replace(/^#+\s*/, '')}</h2> : <p key={index}>{line || '\u00a0'}</p>)}</div>
  </article>
}
