import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowUpRight, BookOpen, Sparkles } from 'lucide-react'
import { reflectMemory } from '../api'
import type { ReflectResponse } from '../types'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'

const prompts = [
  'What decisions have we made about memory ingestion?',
  'Summarize the current architecture and its tradeoffs.',
  'What recurring lessons should I remember for coding tasks?',
]

export function ReflectView({ initialQuery = '', onOpenPage }: { initialQuery?: string; onOpenPage: (path: string) => void }) {
  const [query, setQuery] = useState(initialQuery)
  const [result, setResult] = useState<ReflectResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    try {
      setResult(await reflectMemory(query.trim()))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Reflection is unavailable')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="view-stack">
      <div className="page-header">
        <div className="eyebrow">Grounded synthesis</div>
        <h1>Reflect</h1>
        <p>Ask a higher-level question. Reflection retrieves related pages and synthesizes them through the configured provider.</p>
      </div>

      <div className="reflect-layout">
        <section className="panel reflect-prompt-panel">
          <div className="panel-header">
            <div><h2>Question</h2><p>Use this for “why”, “what changed”, and cross-page synthesis.</p></div>
            <Sparkles size={16} className="panel-icon" />
          </div>

          <textarea className="reflect-input" aria-label="Reflection question" placeholder="Ask a question across your memory…"
            value={query} onChange={event => setQuery(event.target.value)}
            onKeyDown={event => {
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault()
                void submit()
              }
            }} />

          <div className="reflect-actions">
            <span><kbd>⌘</kbd><kbd>Enter</kbd> to synthesize</span>
            <button className="primary-button" onClick={() => void submit()} disabled={loading || !query.trim()}>
              <Sparkles size={14} /> Reflect
            </button>
          </div>

          <div className="prompt-suggestions">
            <span>Try asking</span>
            {prompts.map(prompt => <button key={prompt} onClick={() => setQuery(prompt)}>{prompt}</button>)}
          </div>
        </section>

        <section className="panel synthesis-panel">
          <div className="panel-header">
            <div><h2>Synthesis</h2><p>Grounded in retrieved wiki pages</p></div>
            {result && <span className="source-count">{result.sources.length} sources</span>}
          </div>

          {loading && <LoadingState label="Reading across memory…" />}
          {error && <ErrorBanner message={error} onRetry={() => void submit()} />}

          {!loading && !error && !result && (
            <div className="synthesis-empty">
              <span><BookOpen size={20} /></span>
              <strong>Ready for a question</strong>
              <p>Your answer will appear here with the exact pages used as context.</p>
            </div>
          )}

          {result && !loading && (
            <div className="reflection-result">
              <div className="reflection-copy markdown-body compact-markdown">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    table: ({ children, ...props }) => (
                      <div className="markdown-table-wrap">
                        <table {...props}>{children}</table>
                      </div>
                    ),
                  }}
                >
                  {result.reflection}
                </ReactMarkdown>
              </div>
              <div className="source-heading">Sources</div>
              <div className="source-list">
                {result.sources.map(source => <button key={source.path} className="source-link"
                  onClick={() => onOpenPage(source.path)} aria-label={'Source ' + source.path}>
                  <span><BookOpen size={13} /> {source.path}</span><ArrowUpRight size={13} />
                </button>)}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
