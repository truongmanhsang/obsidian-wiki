import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from 'react-force-graph-2d'
import { Focus, Maximize2, Network, PinOff, RotateCcw, Search, Settings2, X } from 'lucide-react'
import { getGraph } from '../api'
import { buildRadialPositions } from '../graphLayout'
import {
  DEFAULT_GRAPH_SETTINGS,
  GRAPH_PAGE_TYPES,
  filterGraph,
  loadGraphSettings,
  normalizeGraphType,
  type GraphLayoutMode,
  type GraphPageType,
  type GraphSettings,
} from '../graphSettings'
import type { GraphLink, GraphNode, GraphResponse } from '../types'
import { ErrorBanner } from './ErrorBanner'
import { LoadingState } from './LoadingState'

type CanvasNode = NodeObject<GraphNode> & GraphNode & { degree?: number }
type CanvasLink = LinkObject<GraphNode, GraphLink> & GraphLink

function linkId(value: string | CanvasNode | undefined) {
  if (value && typeof value === 'object') return String(value.id ?? value.path ?? '')
  return String(value ?? '')
}

function useCanvasSize() {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 820, height: 680 })

  useEffect(() => {
    const element = ref.current
    if (!element) return
    const update = () => {
      const rect = element.getBoundingClientRect()
      if (rect.width > 0) setSize({ width: Math.floor(rect.width), height: Math.max(520, Math.floor(rect.height || 680)) })
    }
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return { ref, size }
}

function nodeTypeLabel(type: GraphPageType) {
  return type === 'source' ? 'Sources' : type.charAt(0).toUpperCase() + type.slice(1)
}

type PinnedPosition = { x: number; y: number }

function loadPinnedPositions(layoutMode: GraphLayoutMode): Record<string, PinnedPosition> {
  try {
    const raw = localStorage.getItem(`memory-graph-pins-${layoutMode}-v1`)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, PinnedPosition>
    return Object.fromEntries(
      Object.entries(parsed).filter(([, value]) =>
        Number.isFinite(value?.x) && Number.isFinite(value?.y),
      ),
    )
  } catch {
    return {}
  }
}

function savePinnedPositions(layoutMode: GraphLayoutMode, positions: Record<string, PinnedPosition>) {
  localStorage.setItem(`memory-graph-pins-${layoutMode}-v1`, JSON.stringify(positions))
}

export function GraphView({ onOpenPage }: { onOpenPage: (path: string) => void }) {
  const [graph, setGraph] = useState<GraphResponse | null>(null)
  const [settings, setSettings] = useState<GraphSettings>(() => loadGraphSettings())
  const [settingsOpen, setSettingsOpen] = useState(true)
  const [hoverNode, setHoverNode] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [focusedNode, setFocusedNode] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [pinVersion, setPinVersion] = useState(0)
  const graphRef = useRef<ForceGraphMethods<GraphNode, GraphLink> | undefined>(undefined)
  const pinnedPositions = useRef<Record<GraphLayoutMode, Record<string, PinnedPosition>>>({
    radial: loadPinnedPositions('radial'),
    force: loadPinnedPositions('force'),
  })
  const { ref: canvasRef, size } = useCanvasSize()

  useEffect(() => {
    let active = true
    setLoading(true)
    getGraph()
      .then(value => active && setGraph(value))
      .catch(reason => active && setError(reason instanceof Error ? reason.message : 'Graph unavailable'))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [])

  useEffect(() => {
    localStorage.setItem('memory-graph-settings-v1', JSON.stringify(settings))
  }, [settings])

  const filtered = useMemo(() => graph ? filterGraph(graph.nodes, graph.links, settings) : null, [graph, settings])

  const graphData = useMemo(() => {
    if (!filtered) return { nodes: [] as CanvasNode[], links: [] as CanvasLink[] }
    const radialPositions = settings.layoutMode === 'radial'
      ? buildRadialPositions(filtered.nodes, filtered.degrees)
      : new Map()

    return {
      nodes: filtered.nodes.map(node => {
        const pinned = pinnedPositions.current[settings.layoutMode][node.id]
        const radial = radialPositions.get(node.id)
        const position = pinned ?? radial
        return {
          ...node,
          degree: filtered.degrees.get(node.id) ?? 0,
          ...(position ? { fx: position.x, fy: position.y, x: position.x, y: position.y } : {}),
        }
      }) as CanvasNode[],
      links: filtered.links.map(link => ({ ...link })) as CanvasLink[],
    }
  }, [filtered, settings.layoutMode, pinVersion])

  const neighbors = useMemo(() => {
    const map = new Map<string, Set<string>>()
    graphData.nodes.forEach(node => map.set(node.id, new Set()))
    graphData.links.forEach(link => {
      const source = linkId(link.source)
      const target = linkId(link.target)
      map.get(source)?.add(target)
      map.get(target)?.add(source)
    })
    return map
  }, [graphData])

  useEffect(() => {
    if (!graphData.nodes.length) return
    const timer = window.setTimeout(() => graphRef.current?.zoomToFit(500, 42), 100)
    return () => window.clearTimeout(timer)
  }, [graphData.nodes.length, graphData.links.length])

  const highlighted = useMemo(() => {
    const anchor = hoverNode ?? focusedNode
    if (!anchor) return new Set<string>()
    return new Set([anchor, ...(neighbors.get(anchor) ?? [])])
  }, [hoverNode, focusedNode, neighbors])

  const updateSettings = (patch: Partial<GraphSettings>) => setSettings(current => ({ ...current, ...patch }))

  const setTypeEnabled = (type: GraphPageType, enabled: boolean) => {
    setSettings(current => ({
      ...current,
      enabledTypes: { ...current.enabledTypes, [type]: enabled },
    }))
  }

  const setTypeColor = (type: GraphPageType, color: string) => {
    setSettings(current => ({
      ...current,
      colors: { ...current.colors, [type]: color },
    }))
  }

  const focusSearch = () => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return
    const node = graphData.nodes.find(item =>
      item.title.toLowerCase().includes(query)
      || item.path.toLowerCase().includes(query)
      || item.tags.some(tag => tag.toLowerCase().includes(query)),
    )
    if (!node) return
    setFocusedNode(node.id)
    if (typeof node.x === 'number' && typeof node.y === 'number') {
      graphRef.current?.centerAt(node.x, node.y, 650)
      graphRef.current?.zoom(4.2, 650)
    }
  }

  const resetSettings = () => {
    setSettings(structuredClone(DEFAULT_GRAPH_SETTINGS))
    setFocusedNode(null)
  }

  const releasePinnedNodes = () => {
    pinnedPositions.current[settings.layoutMode] = {}
    savePinnedPositions(settings.layoutMode, {})
    setFocusedNode(null)
    setPinVersion(version => version + 1)
    if (settings.layoutMode === 'force') graphRef.current?.d3ReheatSimulation()
  }

  if (loading) return <LoadingState label="Mapping vault links…" />
  if (error) return <ErrorBanner message={error} />
  if (!graph || !filtered) return <ErrorBanner message="Graph data is unavailable." />

  const hiddenCount = graph.count.nodes - filtered.nodes.length

  return (
    <div className="view-stack graph-view">
      <div className="page-header-row graph-page-header">
        <div className="page-header">
          <div className="eyebrow">Knowledge topology</div>
          <h1>Graph</h1>
          <p>Explore pages by their wiki-link relationships. Click a node to open it; drag, pan, and zoom to inspect clusters.</p>
        </div>
        <div className="graph-header-stats" aria-label="Graph statistics">
          <span><strong>{filtered.nodes.length.toLocaleString()}</strong> nodes</span>
          <span><strong>{filtered.links.length.toLocaleString()}</strong> links</span>
          {hiddenCount > 0 && <span>{hiddenCount.toLocaleString()} hidden</span>}
        </div>
      </div>

      <section className="panel graph-shell">
        <div className="graph-toolbar">
          <div className="graph-search">
            <Search size={14} />
            <input
              value={searchQuery}
              onChange={event => setSearchQuery(event.target.value)}
              onKeyDown={event => event.key === 'Enter' && focusSearch()}
              placeholder="Find a node…"
              aria-label="Find graph node"
            />
            {searchQuery && <button aria-label="Clear graph search" onClick={() => { setSearchQuery(''); setFocusedNode(null) }}><X size={13} /></button>}
          </div>
          <button className="secondary-button compact-button" onClick={focusSearch} disabled={!searchQuery.trim()}><Focus size={14} /> Focus</button>
          <div className="graph-toolbar-spacer" />
          <button className="icon-button graph-tool-button" aria-label="Fit graph to view" onClick={() => graphRef.current?.zoomToFit(500, 42)}><Maximize2 size={15} /></button>
          <button className="icon-button graph-tool-button" aria-label="Release pinned nodes" title="Release pinned nodes" onClick={releasePinnedNodes}><PinOff size={15} /></button>
          <button className={`icon-button graph-tool-button ${settingsOpen ? 'active' : ''}`} aria-label="Toggle graph settings" onClick={() => setSettingsOpen(value => !value)}><Settings2 size={15} /></button>
        </div>

        <div className={`graph-main ${settingsOpen ? 'settings-visible' : ''}`}>
          <div className="graph-canvas" ref={canvasRef}>
            {!graphData.nodes.length ? (
              <div className="graph-empty">
                <Network size={24} />
                <strong>No nodes match these filters</strong>
                <span>Lower the connection threshold or enable more page types.</span>
              </div>
            ) : (
              <ForceGraph2D<GraphNode, GraphLink>
                ref={graphRef}
                width={size.width}
                height={size.height}
                graphData={graphData}
                nodeId="id"
                backgroundColor="rgba(0,0,0,0)"
                minZoom={0.15}
                maxZoom={12}
                nodeRelSize={4}
                warmupTicks={settings.layoutMode === 'radial' ? 0 : 40}
                cooldownTicks={settings.layoutMode === 'radial' ? 0 : 160}
                d3VelocityDecay={0.32}
                linkColor={link => {
                  const source = linkId(link.source)
                  const target = linkId(link.target)
                  const active = hoverNode && (source === hoverNode || target === hoverNode)
                  return active ? `rgba(148,163,184,${Math.min(0.95, settings.linkOpacity + 0.5)})` : `rgba(148,163,184,${settings.linkOpacity})`
                }}
                linkWidth={link => {
                  const source = linkId(link.source)
                  const target = linkId(link.target)
                  return hoverNode && (source === hoverNode || target === hoverNode) ? 1.8 : Math.min(1.3, 0.45 + Math.log2((link.weight ?? 1) + 1) * 0.2)
                }}
                nodePointerAreaPaint={(node, color, ctx) => {
                  const radius = (5 + Math.min(8, Math.sqrt(node.degree ?? 0) * 1.4)) * settings.nodeScale
                  ctx.fillStyle = color
                  ctx.beginPath()
                  ctx.arc(node.x ?? 0, node.y ?? 0, radius + 3, 0, Math.PI * 2)
                  ctx.fill()
                }}
                nodeCanvasObject={(node, ctx, globalScale) => {
                  const type = normalizeGraphType(node.type)
                  const color = type ? settings.colors[type] : '#94a3b8'
                  const degree = node.degree ?? 0
                  const active = highlighted.has(node.id)
                  const hasHighlight = highlighted.size > 0
                  const radius = (3.2 + Math.min(7.5, Math.sqrt(degree) * 1.4)) * settings.nodeScale

                  ctx.save()
                  ctx.globalAlpha = hasHighlight && !active ? 0.18 : 1
                  ctx.fillStyle = color
                  ctx.beginPath()
                  ctx.arc(node.x ?? 0, node.y ?? 0, active ? radius * 1.22 : radius, 0, Math.PI * 2)
                  ctx.fill()

                  if (active) {
                    ctx.strokeStyle = 'rgba(255,255,255,0.8)'
                    ctx.lineWidth = 1.1 / globalScale
                    ctx.stroke()
                  }

                  const showLabel = active || (settings.showLabels && (globalScale >= 1.15 || degree >= 8))
                  if (showLabel) {
                    const fontSize = Math.max(3.2, 11 / globalScale)
                    ctx.font = `${fontSize}px Inter, ui-sans-serif, system-ui, sans-serif`
                    ctx.textAlign = 'left'
                    ctx.textBaseline = 'middle'
                    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#e5e7eb'
                    ctx.globalAlpha = hasHighlight && !active ? 0.3 : 0.92
                    ctx.fillText(node.title, (node.x ?? 0) + radius + 2 / globalScale, node.y ?? 0)
                  }
                  ctx.restore()
                }}
                nodeLabel={node => `${node.title} · ${node.type} · ${node.degree ?? 0} connections`}
                onNodeHover={node => setHoverNode(node?.id ? String(node.id) : null)}
                onNodeDragEnd={node => {
                  if (typeof node.x !== 'number' || typeof node.y !== 'number') return
                  node.fx = node.x
                  node.fy = node.y
                  pinnedPositions.current[settings.layoutMode] = {
                    ...pinnedPositions.current[settings.layoutMode],
                    [String(node.id)]: { x: node.x, y: node.y },
                  }
                  savePinnedPositions(settings.layoutMode, pinnedPositions.current[settings.layoutMode])
                }}
                onNodeClick={node => {
                  if (node.type === 'source') {
                    setFocusedNode(node.id)
                    if (typeof node.x === 'number' && typeof node.y === 'number') {
                      graphRef.current?.centerAt(node.x, node.y, 450)
                      graphRef.current?.zoom(3.4, 450)
                    }
                    return
                  }
                  onOpenPage(node.path)
                }}
                onBackgroundClick={() => { setHoverNode(null); setFocusedNode(null) }}
              />
            )}

            <div className="graph-legend" aria-label="Graph legend">
              {GRAPH_PAGE_TYPES.filter(type => !(settings.ignoreSources && type === 'source') && settings.enabledTypes[type]).map(type => (
                <span key={type}><i style={{ background: settings.colors[type] }} />{nodeTypeLabel(type)}</span>
              ))}
            </div>
          </div>

          {settingsOpen && (
            <aside className="graph-settings" aria-label="Graph settings">
              <div className="graph-settings-header">
                <div><strong>Graph settings</strong><span>Display & filters</span></div>
                <button className="text-button" onClick={resetSettings}><RotateCcw size={12} /> Reset</button>
              </div>

              <div className="graph-setting-section">
                <div className="graph-setting-title">Layout</div>
                <div className="graph-layout-options" role="radiogroup" aria-label="Graph layout">
                  <button
                    className={settings.layoutMode === 'radial' ? 'active' : ''}
                    onClick={() => updateSettings({ layoutMode: 'radial' })}
                    role="radio"
                    aria-checked={settings.layoutMode === 'radial'}
                  >
                    <strong>Radial</strong>
                    <span>Even circular distribution</span>
                  </button>
                  <button
                    className={settings.layoutMode === 'force' ? 'active' : ''}
                    onClick={() => updateSettings({ layoutMode: 'force' })}
                    role="radio"
                    aria-checked={settings.layoutMode === 'force'}
                  >
                    <strong>Force</strong>
                    <span>Relationship-driven clusters</span>
                  </button>
                </div>
              </div>

              <div className="graph-setting-section">
                <label className="toggle-row">
                  <span><strong>Ignore sources/</strong><small>Hide raw session transcripts</small></span>
                  <input type="checkbox" checked={settings.ignoreSources} onChange={event => updateSettings({ ignoreSources: event.target.checked })} />
                </label>
                <label className="toggle-row">
                  <span><strong>Show labels</strong><small>Labels appear as you zoom in</small></span>
                  <input type="checkbox" checked={settings.showLabels} onChange={event => updateSettings({ showLabels: event.target.checked })} />
                </label>
              </div>

              <div className="graph-setting-section">
                <div className="graph-setting-title">Page types & colors</div>
                <div className="graph-type-list">
                  {GRAPH_PAGE_TYPES.map(type => (
                    <div className={`graph-type-row ${settings.ignoreSources && type === 'source' ? 'disabled' : ''}`} key={type}>
                      <input
                        type="checkbox"
                        aria-label={`Show ${type} nodes`}
                        checked={settings.enabledTypes[type]}
                        disabled={settings.ignoreSources && type === 'source'}
                        onChange={event => setTypeEnabled(type, event.target.checked)}
                      />
                      <span>{nodeTypeLabel(type)}</span>
                      <input
                        type="color"
                        aria-label={`${type} node color`}
                        value={settings.colors[type]}
                        disabled={settings.ignoreSources && type === 'source'}
                        onChange={event => setTypeColor(type, event.target.value)}
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div className="graph-setting-section range-settings">
                <label>
                  <span><strong>Minimum connections</strong><output>{settings.minConnections}</output></span>
                  <input type="range" min="0" max="12" step="1" value={settings.minConnections} onChange={event => updateSettings({ minConnections: Number(event.target.value) })} />
                </label>
                <label>
                  <span><strong>Node size</strong><output>{settings.nodeScale.toFixed(1)}×</output></span>
                  <input type="range" min="0.6" max="2" step="0.1" value={settings.nodeScale} onChange={event => updateSettings({ nodeScale: Number(event.target.value) })} />
                </label>
                <label>
                  <span><strong>Link opacity</strong><output>{Math.round(settings.linkOpacity * 100)}%</output></span>
                  <input type="range" min="0.08" max="0.8" step="0.04" value={settings.linkOpacity} onChange={event => updateSettings({ linkOpacity: Number(event.target.value) })} />
                </label>
              </div>
            </aside>
          )}
        </div>
      </section>
    </div>
  )
}
