import { describe, expect, it } from 'vitest'
import { buildRadialPositions } from './graphLayout'
import type { GraphNode } from './types'

const node = (id: string): GraphNode => ({ id, path: id, title: id, type: 'concept', updated: '', tags: [] })

describe('radial graph layout', () => {
  it('places the highest-degree node at the center and spreads others outward', () => {
    const nodes = [node('a.md'), node('b.md'), node('c.md'), node('d.md')]
    const positions = buildRadialPositions(nodes, new Map([
      ['a.md', 1],
      ['b.md', 9],
      ['c.md', 3],
      ['d.md', 2],
    ]))

    expect(positions.get('b.md')).toEqual({ x: 0, y: 0 })
    const radii = ['a.md', 'c.md', 'd.md'].map(id => {
      const pos = positions.get(id)!
      return Math.hypot(pos.x, pos.y)
    })
    expect(Math.min(...radii)).toBeGreaterThan(0)
    expect(new Set(radii.map(value => Math.round(value))).size).toBe(3)
  })

  it('is deterministic regardless of input node order', () => {
    const nodes = [node('a.md'), node('b.md'), node('c.md')]
    const degrees = new Map(nodes.map(item => [item.id, 1]))
    expect([...buildRadialPositions(nodes, degrees)]).toEqual([...buildRadialPositions([...nodes].reverse(), degrees)])
  })
})
