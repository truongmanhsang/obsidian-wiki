import { ArrowUpRight, FileText } from 'lucide-react'
import type { MemoryResult } from '../types'

export function ResultCard({ result, onOpen }: { result: MemoryResult; onOpen: (path: string) => void }) {
  return (
    <button className="result-card" onClick={() => onOpen(result.path)} aria-label={result.title}>
      <span className="result-card-icon"><FileText size={17} /></span>
      <span className="result-card-main">
        <span className="result-card-title">{result.title}</span>
        <span className="result-card-path">{result.path}</span>
        {result.snippet && <span className="result-card-snippet">{result.snippet}</span>}
      </span>
      <span className="result-card-meta"><span className="type-pill">{result.type}</span><ArrowUpRight size={16} /></span>
    </button>
  )
}
