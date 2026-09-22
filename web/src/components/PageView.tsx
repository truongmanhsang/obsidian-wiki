import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, FileText } from 'lucide-react'
import { readPage, resolveWikiLink } from '../api'
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

function headingId(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g, '$1')
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
}

type WikiLinkHandler = (target: string) => void

function renderInline(text: string, onWikiLink: WikiLinkHandler) {
  const nodes: React.ReactNode[] = []
  const pattern = /\[\[([^\]]+)\]\]/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index))

    const raw = match[1].trim()
    const separator = raw.indexOf('|')
    const target = (separator >= 0 ? raw.slice(0, separator) : raw).trim()
    const label = (separator >= 0 ? raw.slice(separator + 1) : raw.split('#')[0]).trim() || target

    nodes.push(
      <a
        href={`#wiki:${encodeURIComponent(target)}`}
        className="wiki-link"
        key={`${match.index}-${target}`}
        onClick={event => {
          event.preventDefault()
          onWikiLink(target)
        }}
      >
        {label}
      </a>,
    )
    cursor = pattern.lastIndex
  }

  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

function renderMarkdown(body: string, onWikiLink: WikiLinkHandler) {
  const lines = body.split('\n')
  const blocks: React.ReactNode[] = []
  let list: string[] = []

  const flushList = () => {
    if (!list.length) return
    const items = list
    list = []
    blocks.push(<ul key={'list-' + blocks.length}>{items.map((item, index) => <li key={index}>{renderInline(item, onWikiLink)}</li>)}</ul>)
  }

  lines.forEach((line, index) => {
    const trimmed = line.trim()
    if (trimmed.startsWith('- ')) {
      list.push(trimmed.slice(2))
      return
    }

    flushList()
    if (!trimmed) return
    if (/^###\s+/.test(trimmed)) {
      const value = trimmed.replace(/^###\s+/, '')
      blocks.push(<h3 id={headingId(value)} key={index}>{renderInline(value, onWikiLink)}</h3>)
    } else if (/^##\s+/.test(trimmed)) {
      const value = trimmed.replace(/^##\s+/, '')
      blocks.push(<h2 id={headingId(value)} key={index}>{renderInline(value, onWikiLink)}</h2>)
    } else if (/^#\s+/.test(trimmed)) {
      const value = trimmed.replace(/^#\s+/, '')
      blocks.push(<h1 id={headingId(value)} key={index}>{renderInline(value, onWikiLink)}</h1>)
    } else if (/^>\s?/.test(trimmed)) {
      blocks.push(<blockquote key={index}>{renderInline(trimmed.replace(/^>\s?/, ''), onWikiLink)}</blockquote>)
    } else if (/^\`\`\`/.test(trimmed)) return
    else blocks.push(<p key={index}>{renderInline(trimmed, onWikiLink)}</p>)
  })

  flushList()
  return blocks
}

export function PageView({
  path,
  onBack,
  onOpenPage,
}: {
  path: string
  onBack: () => void
  onOpenPage: (path: string) => void
}) {
  const [page, setPage] = useState<MemoryPageDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [linkError, setLinkError] = useState<string | null>(null)
  const [pendingFragment, setPendingFragment] = useState('')

  useEffect(() => {
    let active = true
    setPage(null)
    setError(null)
    setLinkError(null)
    readPage(path).then(value => active && setPage(value))
      .catch(reason => active && setError(reason instanceof Error ? reason.message : 'Page unavailable'))
    return () => { active = false }
  }, [path])

  const parsed = useMemo(() => page ? stripFrontmatter(page.content) : null, [page])

  useEffect(() => {
    if (!page || !pendingFragment) return
    const id = headingId(pendingFragment)
    window.requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
      setPendingFragment('')
    })
  }, [page, pendingFragment])

  const openWikiLink = async (target: string) => {
    setLinkError(null)
    try {
      const resolved = await resolveWikiLink(target, path)
      setPendingFragment(resolved.fragment)
      if (resolved.path === path && resolved.fragment) {
        const id = headingId(resolved.fragment)
        document.getElementById(id)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
        setPendingFragment('')
        return
      }
      onOpenPage(resolved.path)
    } catch (reason) {
      setLinkError(reason instanceof Error ? reason.message : `Unable to open ${target}`)
    }
  }

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
      {linkError && <ErrorBanner message={linkError} />}
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
      <div className="document-body">{renderMarkdown(parsed.body, openWikiLink)}</div>
      {page.truncated && <div className="truncated-note">This document is truncated at the API read limit.</div>}
    </article>
  )
}
