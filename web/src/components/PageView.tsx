import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, FileText } from 'lucide-react'
import { readPage } from '../api'
import type { MemoryPageDetail } from '../types'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'

function stripFrontmatter(content: string) {
  if (!content.startsWith('---\n')) return { body: content, meta: {} as Record<string, string> }
  const end = content.indexOf('\n---', 4)
  if (end === -1) return { body: content, meta: {} as Record<string, string> }

  const meta: Record<string, string> = {}
  content.slice(4, end).split('\n').forEach(line => {
    const separator = line.indexOf(':')
    if (separator > 0) meta[line.slice(0, separator).trim()] = line.slice(separator + 1).trim()
  })
  return { body: content.slice(end + 4).trimStart(), meta }
}

function renderMarkdown(body: string) {
  const lines = body.split('\n')
  const blocks: React.ReactNode[] = []
  let list: string[] = []

  const flushList = () => {
    if (!list.length) return
    const items = list
    list = []
    blocks.push(<ul key={'list-' + blocks.length}>{items.map((item, index) => <li key={index}>{item}</li>)}</ul>)
  }

  lines.forEach((line, index) => {
    const trimmed = line.trim()
    if (trimmed.startsWith('- ')) {
      list.push(trimmed.slice(2))
      return
    }

    flushList()
    if (!trimmed) return
    if (/^###\s+/.test(trimmed)) blocks.push(<h3 key={index}>{trimmed.replace(/^###\s+/, '')}</h3>)
    else if (/^##\s+/.test(trimmed)) blocks.push(<h2 key={index}>{trimmed.replace(/^##\s+/, '')}</h2>)
    else if (/^#\s+/.test(trimmed)) blocks.push(<h1 key={index}>{trimmed.replace(/^#\s+/, '')}</h1>)
    else if (/^>\s?/.test(trimmed)) blocks.push(<blockquote key={index}>{trimmed.replace(/^>\s?/, '')}</blockquote>)
    else if (/^\`\`\`/.test(trimmed)) return
    else blocks.push(<p key={index}>{trimmed}</p>)
  })

  flushList()
  return blocks
}

export function PageView({ path, onBack }: { path: string; onBack: () => void }) {
  const [page, setPage] = useState<MemoryPageDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setPage(null)
    setError(null)
    readPage(path).then(value => active && setPage(value))
      .catch(reason => active && setError(reason instanceof Error ? reason.message : 'Page unavailable'))
    return () => { active = false }
  }, [path])

  const parsed = useMemo(() => page ? stripFrontmatter(page.content) : null, [page])

  if (error) return <>
    <button className="back-button" onClick={onBack}><ArrowLeft size={15} /> Back</button>
    <ErrorBanner message={error} />
  </>

  if (!page || !parsed) return <LoadingState label="Opening document…" />

  const title = parsed.body.split('\n').find(line => line.startsWith('# '))?.slice(2)
    ?? page.path.split('/').pop()?.replace('.md', '')
    ?? page.path

  return (
    <article className="document-view">
      <button className="back-button" onClick={onBack}><ArrowLeft size={15} /> Back to workspace</button>
      <div className="document-header">
        <div className="document-icon"><FileText size={18} /></div>
        <div>
          <div className="document-path">{page.path}</div>
          <h1>{title}</h1>
          <div className="document-meta">
            {parsed.meta.type && <span className="type-pill">{parsed.meta.type}</span>}
            {parsed.meta.updated && <span>Updated {parsed.meta.updated}</span>}
            <span className="revision">rev {page.revision.slice(0, 8)}</span>
          </div>
        </div>
      </div>
      <div className="document-divider" />
      <div className="document-body">{renderMarkdown(parsed.body)}</div>
      {page.truncated && <div className="truncated-note">This document is truncated at the API read limit.</div>}
    </article>
  )
}
