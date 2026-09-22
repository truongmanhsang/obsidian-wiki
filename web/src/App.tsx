import { useEffect, useRef, useState } from 'react'
import {
  Activity,
  Database,
  LibraryBig,
  Moon,
  Search,
  Sparkles,
  Sun,
  LayoutDashboard,
} from 'lucide-react'
import { BrowseView } from './components/BrowseView'
import { OperationsView } from './components/OperationsView'
import { OverviewView } from './components/OverviewView'
import { PageView } from './components/PageView'
import { ReflectView } from './components/ReflectView'
import { SearchView } from './components/SearchView'

export type View = 'overview' | 'search' | 'library' | 'reflect' | 'operations' | 'page'

const navigation: Array<{ id: Exclude<View, 'page'>; label: string; icon: typeof Search }> = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'search', label: 'Search', icon: Search },
  { id: 'library', label: 'Library', icon: LibraryBig },
  { id: 'reflect', label: 'Reflect', icon: Sparkles },
  { id: 'operations', label: 'Operations', icon: Activity },
]

const titles: Record<Exclude<View, 'page'>, string> = {
  overview: 'Overview',
  search: 'Search',
  library: 'Library',
  reflect: 'Reflect',
  operations: 'Operations',
}

export default function App() {
  const [view, setView] = useState<View>('overview')
  const [dark, setDark] = useState(() => localStorage.getItem('memory-theme') !== 'light')
  const [pagePath, setPagePath] = useState<string | null>(null)
  const [returnView, setReturnView] = useState<View>('search')
  const [reflectQuery, setReflectQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('memory-theme', dark ? 'dark' : 'light')
  }, [dark])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      const editing = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
      const wantsSearch = (event.key === '/' && !editing) || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k')
      if (!wantsSearch) return
      event.preventDefault()
      setView('search')
      window.setTimeout(() => searchRef.current?.focus(), 0)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const openPage = (path: string, from: View) => {
    setPagePath(path)
    setReturnView(from)
    setView('page')
  }

  const navigate = (next: Exclude<View, 'page'>) => {
    setView(next)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <span className="brand-mark"><Database size={16} /></span>
          <span>
            <strong className="brand-name">Obsidian Memory</strong>
            <span className="brand-caption">Hermes knowledge layer</span>
          </span>
        </div>

        <div className="sidebar-label">Workspace</div>
        <nav className="nav-list" aria-label="Primary navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-button ${view === id ? 'active' : ''}`}
              onClick={() => navigate(id)}
              aria-current={view === id ? 'page' : undefined}
            >
              <Icon size={16} strokeWidth={1.9} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="endpoint-card">
            <div className="endpoint-line">
              <span className="status-dot" />
              <span>Local MCP</span>
              <span className="endpoint-state">ready</span>
            </div>
            <code>127.0.0.1:8765</code>
          </div>
          <button
            className="theme-button"
            onClick={() => setDark(value => !value)}
            aria-label={dark ? 'Use light theme' : 'Use dark theme'}
          >
            {dark ? <Sun size={15} /> : <Moon size={15} />}
            <span>{dark ? 'Light appearance' : 'Dark appearance'}</span>
          </button>
        </div>
      </aside>

      <main className="workspace" aria-label="Memory workspace">
        <header className="topbar">
          <div className="topbar-title">
            <span className="topbar-product">Memory</span>
            <span className="topbar-slash">/</span>
            <strong>{view === 'page' ? 'Document' : titles[view]}</strong>
          </div>
          <button className="command-trigger" onClick={() => navigate('search')}>
            <Search size={14} />
            <span>Search memory</span>
            <kbd>⌘ K</kbd>
          </button>
        </header>

        <section className="content-column">
          {view === 'page' && pagePath ? (
            <PageView
              path={pagePath}
              onBack={() => setView(returnView === 'page' ? 'search' : returnView)}
              onOpenPage={setPagePath}
            />
          ) : view === 'overview' ? (
            <OverviewView onNavigate={navigate} onOpenPage={path => openPage(path, 'overview')} />
          ) : view === 'library' ? (
            <BrowseView onOpenPage={path => openPage(path, 'library')} />
          ) : view === 'reflect' ? (
            <ReflectView
              initialQuery={reflectQuery}
              onOpenPage={path => openPage(path, 'reflect')}
            />
          ) : view === 'operations' ? (
            <OperationsView />
          ) : (
            <SearchView
              inputRef={searchRef}
              onOpenPage={path => openPage(path, 'search')}
              onReflect={query => {
                setReflectQuery(query)
                setView('reflect')
              }}
            />
          )}
        </section>
      </main>
    </div>
  )
}
