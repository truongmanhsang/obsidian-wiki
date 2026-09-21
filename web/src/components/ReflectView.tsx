import { useState } from 'react'
import { ArrowUpRight, Sparkles } from 'lucide-react'
import { reflectMemory } from '../api'
import type { ReflectResponse } from '../types'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'

export function ReflectView({ initialQuery = '', onOpenPage }: { initialQuery?: string; onOpenPage: (path: string) => void }) {
  const [query, setQuery] = useState(initialQuery)
  const [result, setResult] = useState<ReflectResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function submit() { if (!query.trim()) return; setLoading(true); setError(null); try { setResult(await reflectMemory(query.trim())) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Reflection is unavailable') } finally { setLoading(false) } }
  return <div className="view-stack reflect-view"><div className="view-heading"><div><span className="hero-kicker">Grounded synthesis</span><h1>Reflect with context.</h1><p>Ask a question and let the relevant pages speak together.</p></div><span className="reflect-badge"><Sparkles size={18} /></span></div><textarea className="reflect-input" aria-label="Reflection question" placeholder="What do you want to understand?" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); void submit() } }} /><div className="reflect-actions"><span>⌘ / Ctrl + Enter to synthesize</span><button className="primary-button" onClick={() => void submit()} disabled={loading || !query.trim()}><Sparkles size={15} /> Reflect</button></div>{loading && <LoadingState label="Reading across your memory…" />}{error && <ErrorBanner message={error} onRetry={() => void submit()} />}{result && !loading && <div className="reflection-result"><div className="reflection-label"><Sparkles size={15} /> Reflection</div><div className="reflection-copy">{result.reflection}</div><div className="source-heading">Sources used</div><div className="source-list">{result.sources.map(source => <button key={source.path} className="source-link" onClick={() => onOpenPage(source.path)} aria-label={`Source ${source.path}`}><span>{source.path}</span><ArrowUpRight size={15} /></button>)}</div></div>}</div>
}
