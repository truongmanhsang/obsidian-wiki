import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, ExternalLink, FileText } from 'lucide-react'
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

function textContent(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textContent).join('')
  if (node && typeof node === 'object' && 'props' in node) {
    return textContent((node as { props?: { children?: ReactNode } }).props?.children)
  }
  return ''
}

function markdownLabel(value: string) {
  return value.replace(/([\\\[\]])/g, '\\$1')
}

function replaceWikiLinks(value: string) {
  return value.replace(/\[\[([^\]]+)\]\]/g, (_full, rawValue: string) => {
    const raw = rawValue.trim()
    const separator = raw.indexOf('|')
    const target = (separator >= 0 ? raw.slice(0, separator) : raw).trim()
    const label = (separator >= 0 ? raw.slice(separator + 1) : raw.split('#')[0]).trim() || target
    return `[${markdownLabel(label)}](#wiki:${encodeURIComponent(target)})`
  })
}

function replaceWikiLinksOutsideInlineCode(line: string) {
  let result = ''
  let cursor = 0

  while (cursor < line.length) {
    const tick = line.indexOf('`', cursor)
    if (tick === -1) return result + replaceWikiLinks(line.slice(cursor))

    result += replaceWikiLinks(line.slice(cursor, tick))
    let runLength = 1
    while (line[tick + runLength] === '`') runLength += 1
    const marker = '`'.repeat(runLength)
    const closing = line.indexOf(marker, tick + runLength)
    if (closing === -1) return result + line.slice(tick)

    result += line.slice(tick, closing + runLength)
    cursor = closing + runLength
  }

  return result
}

/**
 * Convert Obsidian wikilinks into ordinary Markdown fragment links so the
 * CommonMark parser can render them. Fenced and inline code stays untouched.
 */
function preprocessWikiLinks(markdown: string) {
  let fenceMarker = ''
  return markdown.split('\n').map(line => {
    const fence = line.match(/^\s*(```+|~~~+)/)?.[1] ?? ''
    if (fence) {
      const marker = fence[0]
      if (!fenceMarker) fenceMarker = marker
      else if (marker === fenceMarker) fenceMarker = ''
      return line
    }
    if (fenceMarker) return line
    return replaceWikiLinksOutsideInlineCode(line)
  }).join('\n')
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
  const markdown = useMemo(() => parsed ? preprocessWikiLinks(parsed.body) : '', [parsed])

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

  const heading = (level: 1 | 2 | 3 | 4 | 5 | 6, children: ReactNode) => {
    const Tag = `h${level}` as keyof React.JSX.IntrinsicElements
    return <Tag id={headingId(textContent(children))}>{children}</Tag>
  }

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
      <div className="document-body markdown-body">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => heading(1, children),
            h2: ({ children }) => heading(2, children),
            h3: ({ children }) => heading(3, children),
            h4: ({ children }) => heading(4, children),
            h5: ({ children }) => heading(5, children),
            h6: ({ children }) => heading(6, children),
            table: ({ children, ...props }) => (
              <div className="markdown-table-wrap">
                <table {...props}>{children}</table>
              </div>
            ),
            img: ({ alt = '', ...props }) => <img {...props} alt={alt} loading="lazy" />,
            a: ({ href = '', children, ...props }) => {
              if (href.startsWith('#wiki:')) {
                const encoded = href.slice('#wiki:'.length)
                let target = encoded
                try { target = decodeURIComponent(encoded) } catch { /* keep encoded target */ }
                return (
                  <a
                    {...props}
                    href={href}
                    className="wiki-link"
                    onClick={event => {
                      event.preventDefault()
                      void openWikiLink(target)
                    }}
                  >
                    {children}
                  </a>
                )
              }

              const external = /^https?:\/\//i.test(href)
              return (
                <a
                  {...props}
                  href={href}
                  className={external ? 'markdown-link external-link' : 'markdown-link'}
                  target={external ? '_blank' : undefined}
                  rel={external ? 'noreferrer noopener' : undefined}
                >
                  {children}
                  {external && <ExternalLink className="external-link-icon" size={11} aria-hidden="true" />}
                </a>
              )
            },
          }}
        >
          {markdown}
        </ReactMarkdown>
      </div>
      {page.truncated && <div className="truncated-note">This document is truncated at the API read limit.</div>}
    </article>
  )
}
