import { describe, expect, it } from 'vitest'
import { DEFAULT_GRAPH_SETTINGS, filterGraph } from './graphSettings'
import type { GraphLink, GraphNode } from './types'

const nodes: GraphNode[] = [
  { id: 'concepts/a.md', path: 'concepts/a.md', title: 'A', type: 'concept', updated: '', tags: [] },
  { id: 'entities/b.md', path: 'entities/b.md', title: 'B', type: 'entity', updated: '', tags: [] },
  { id: 'sources/sessions/c.md', path: 'sources/sessions/c.md', title: 'C', type: 'source', updated: '', tags: [] },
]
const links: GraphLink[] = [
  { source: 'concepts/a.md', target: 'entities/b.md', weight: 1 },
  { source: 'concepts/a.md', target: 'sources/sessions/c.md', weight: 1 },
]

describe('graph settings', () => {
  it('ignores source nodes by default', () => {
    const result = filterGraph(nodes, links, structuredClone(DEFAULT_GRAPH_SETTINGS))
    expect(result.nodes.map(node => node.id)).toEqual(['concepts/a.md', 'entities/b.md'])
    expect(result.links).toHaveLength(1)
  })

  it('filters page types and minimum degree', () => {
    const settings = structuredClone(DEFAULT_GRAPH_SETTINGS)
    settings.ignoreSources = false
    settings.enabledTypes.entity = false
    settings.minConnections = 1
    const result = filterGraph(nodes, links, settings)
    expect(result.nodes.map(node => node.id).sort()).toEqual(['concepts/a.md', 'sources/sessions/c.md'])
    expect(result.links).toHaveLength(1)
  })
})
