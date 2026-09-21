import { useEffect, useRef, useState } from 'react'
import { BookOpen, Compass, Moon, Search, Sparkles, Sun } from 'lucide-react'
import { PageView } from './components/PageView'
import { BrowseView } from './components/BrowseView'
import { ReflectView } from './components/ReflectView'
import { SearchView } from './components/SearchView'

type View = 'search' | 'browse' | 'reflect' | 'page'

const navigation: Array<{ id: View; label: string; icon: typeof Search }> = [
  { id: 'search', label: 'Search', icon: Search },
  { id: 'browse', label: 'Browse', icon: Compass },
  { id: 'reflect', label: 'Reflect', icon: Sparkles },
]

export default function App() {
  const [view, setView] = useState<View>('search')
  const [dark, setDark] = useState(false)
  const [pagePath, setPagePath] = useState<string | null>(null)
  const [returnView, setReturnView] = useState<View>('search')
  const [reflectQuery, setReflectQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    return () => {
      delete document.documentElement.dataset.theme
    }
  }, [dark])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (event.key === '/' && target.tagName !== 'INPUT' && target.tagName !== 'TEXTAREA') {
        event.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><BookOpen size={18} strokeWidth={2.4} /></div>
          <div><div className="brand-name">Memory</div><div className="brand-caption">Obsidian wiki</div></div>
        </div>
        <nav className="nav-list" aria-label="Primary navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-button ${view === id ? 'active' : ''}`} onClick={() => setView(id)} aria-current={view === id ? 'page' : undefined}>
              <Icon size={17} /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="vault-pulse"><span className="pulse-dot" /><span>Vault connected</span></div>
          <button className="theme-button" onClick={() => setDark(value => !value)} aria-label={dark ? 'Use light theme' : 'Use dark theme'}>
            {dark ? <Sun size={16} /> : <Moon size={16} />}<span>{dark ? 'Light mode' : 'Dark mode'}</span>
          </button>
        </div>
      </aside>
      <main className="workspace" aria-label="Memory workspace">
        <header className="workspace-header">
          <div className="eyebrow">Personal knowledge workspace</div>
          <div className="header-hint"><kbd>/</kbd><span>Focus search</span></div>
        </header>
        <section className="content-column">
          {view === 'page' && pagePath ? <PageView path={pagePath} onBack={() => setView(returnView === 'page' ? 'search' : returnView)} /> : view === 'browse' ? <BrowseView onOpenPage={(path) => { setPagePath(path); setReturnView('browse'); setView('page') }} /> : view === 'reflect' ? <ReflectView initialQuery={reflectQuery} onOpenPage={(path) => { setPagePath(path); setReturnView('reflect'); setView('page') }} /> : <SearchView inputRef={searchRef} onOpenPage={(path) => { setPagePath(path); setReturnView('search'); setView('page') }} onReflect={(query) => { setReflectQuery(query); setView('reflect') }} />}
        </section>
      </main>
    </div>
  )
}
