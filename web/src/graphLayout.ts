import type { GraphNode } from './types'

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))
const RADIAL_SPACING = 22

export type GraphPosition = { x: number; y: number }

/**
 * Deterministic sunflower layout: high-degree pages start near the center and
 * the rest fill a circular disk with near-uniform spacing using the golden angle.
 */
export function buildRadialPositions(
  nodes: GraphNode[],
  degrees: Map<string, number>,
): Map<string, GraphPosition> {
  const ordered = [...nodes].sort((a, b) => {
    const degreeDelta = (degrees.get(b.id) ?? 0) - (degrees.get(a.id) ?? 0)
    if (degreeDelta) return degreeDelta
    return a.id.localeCompare(b.id)
  })

  const positions = new Map<string, GraphPosition>()
  ordered.forEach((node, index) => {
    if (index === 0) {
      positions.set(node.id, { x: 0, y: 0 })
      return
    }
    const radius = RADIAL_SPACING * Math.sqrt(index)
    const angle = index * GOLDEN_ANGLE
    positions.set(node.id, {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    })
  })
  return positions
}
