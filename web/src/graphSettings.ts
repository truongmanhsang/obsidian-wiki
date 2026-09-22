import type { GraphLink, GraphNode, PageType } from './types'

export const GRAPH_PAGE_TYPES = [
  'concept',
  'entity',
  'person',
  'decision',
  'environment',
  'answer',
  'preference',
  'source',
] as const

export type GraphPageType = typeof GRAPH_PAGE_TYPES[number]

export type GraphSettings = {
  ignoreSources: boolean
  enabledTypes: Record<GraphPageType, boolean>
  colors: Record<GraphPageType, string>
  showLabels: boolean
  minConnections: number
  nodeScale: number
  linkOpacity: number
}

export const DEFAULT_GRAPH_SETTINGS: GraphSettings = {
  ignoreSources: true,
  enabledTypes: {
    concept: true,
    entity: true,
    person: true,
    decision: true,
    environment: true,
    answer: true,
    preference: true,
    source: true,
  },
  colors: {
    concept: '#8b5cf6',
    entity: '#14b8a6',
    person: '#f59e0b',
    decision: '#ef4444',
    environment: '#06b6d4',
    answer: '#22c55e',
    preference: '#ec4899',
    source: '#64748b',
  },
  showLabels: true,
  minConnections: 0,
  nodeScale: 1,
  linkOpacity: 0.24,
}

export function normalizeGraphType(type: PageType): GraphPageType | null {
  return (GRAPH_PAGE_TYPES as readonly string[]).includes(String(type))
    ? type as GraphPageType
    : null
}

export function loadGraphSettings(storage: Pick<Storage, 'getItem'> = localStorage): GraphSettings {
  try {
    const raw = storage.getItem('memory-graph-settings-v1')
    if (!raw) return structuredClone(DEFAULT_GRAPH_SETTINGS)
    const parsed = JSON.parse(raw) as Partial<GraphSettings>
    return {
      ...structuredClone(DEFAULT_GRAPH_SETTINGS),
      ...parsed,
      enabledTypes: { ...DEFAULT_GRAPH_SETTINGS.enabledTypes, ...(parsed.enabledTypes ?? {}) },
      colors: { ...DEFAULT_GRAPH_SETTINGS.colors, ...(parsed.colors ?? {}) },
    }
  } catch {
    return structuredClone(DEFAULT_GRAPH_SETTINGS)
  }
}

export function filterGraph(
  nodes: GraphNode[],
  links: GraphLink[],
  settings: GraphSettings,
): { nodes: GraphNode[]; links: GraphLink[]; degrees: Map<string, number> } {
  const typeVisible = (node: GraphNode) => {
    const type = normalizeGraphType(node.type)
    if (!type) return true
    if (settings.ignoreSources && type === 'source') return false
    return settings.enabledTypes[type]
  }

  const initialNodes = nodes.filter(typeVisible)
  const initialIds = new Set(initialNodes.map(node => node.id))
  const initialLinks = links.filter(link => initialIds.has(String(link.source)) && initialIds.has(String(link.target)))
  const initialDegrees = new Map<string, number>()
  initialNodes.forEach(node => initialDegrees.set(node.id, 0))
  initialLinks.forEach(link => {
    const source = String(link.source)
    const target = String(link.target)
    initialDegrees.set(source, (initialDegrees.get(source) ?? 0) + 1)
    initialDegrees.set(target, (initialDegrees.get(target) ?? 0) + 1)
  })

  const nodesAfterDegree = settings.minConnections > 0
    ? initialNodes.filter(node => (initialDegrees.get(node.id) ?? 0) >= settings.minConnections)
    : initialNodes
  const ids = new Set(nodesAfterDegree.map(node => node.id))
  const visibleLinks = initialLinks.filter(link => ids.has(String(link.source)) && ids.has(String(link.target)))
  const degrees = new Map<string, number>()
  nodesAfterDegree.forEach(node => degrees.set(node.id, 0))
  visibleLinks.forEach(link => {
    const source = String(link.source)
    const target = String(link.target)
    degrees.set(source, (degrees.get(source) ?? 0) + 1)
    degrees.set(target, (degrees.get(target) ?? 0) + 1)
  })

  return { nodes: nodesAfterDegree, links: visibleLinks, degrees }
}
