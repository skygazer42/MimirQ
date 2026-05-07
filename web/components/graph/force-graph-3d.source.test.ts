import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('force graph 3d source', () => {
  it('uses graph data color, weight, and relation labels for the default 3D graph', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'force-graph-3d.tsx'), 'utf8')

    expect(src).toContain("String(link?.color || '').trim() || EDGE_KIND_COLORS[kind]")
    expect(src).toContain('showEdgeLabels = false')
    expect(src).toContain('allowLinkLabelSprites')
    expect(src).toContain('linkThreeObject={')
    expect(src).toContain('? (link: any) => {')
    expect(src).toContain('new SpriteText(label)')
    expect(src).toContain('nodeVal="val"')
  })

  it('downgrades heavy 3D affordances for large graphs and during drag', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'force-graph-3d.tsx'), 'utf8')

    expect(src).toContain('const isLargeGraph = data.nodes.length > 180 || data.links.length > 360')
    expect(src).toContain('const useCustomNodeObjects = !isLargeGraph && data.nodes.length <= 36')
    expect(src).toContain('const nodeRelSize = isLargeGraph ? 3.8 : GRAPH_3D_NODE_REL_SIZE')
    expect(src).toContain('const nodeResolution = isLargeGraph ? 8 : 16')
    expect(src).toContain('cooldownTicks={cooldownTicks}')
    expect(src).toContain('cooldownTime={cooldownTime}')
    expect(src).toContain('enableNodeDrag={!isLargeGraph}')
    expect(src).toContain('nodeThreeObjectExtend={useCustomNodeObjects}')
  })
})
