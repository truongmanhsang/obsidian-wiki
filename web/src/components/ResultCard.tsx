import { ArrowUpRight, FileText } from 'lucide-react'
import type { MemoryResult } from '../types'

function scoreLabel(score?: number) {
  if (score === undefined || score === null || Number.isNaN(score)) return null
  const value = score <= 1 ? Math.round(score * 100) : Math.round(score)
  return String(value) + '%'
}

export function ResultCard({ result, onOpen }: { result: MemoryResult; onOpen: (path: string) => void }) {
  const score = scoreLabel(result.score)
  return (
    <button className="result-card" onClick={() => onOpen(result.path)} aria-label={result.title}>
      <span className="result-card-icon"><FileText size={15} /></span>
      <span className="result-card-main">
        <span className="result-title-line"><strong>{result.title}</strong><span className="type-pill">{result.type}</span></span>
        <span className="result-path">{result.path}</span>
        {result.snippet && <span className="result-snippet">{result.snippet}</span>}
      </span>
      <span className="result-card-meta">{score && <small>{score}</small>}<ArrowUpRight size={14} /></span>
    </button>
  )
}
