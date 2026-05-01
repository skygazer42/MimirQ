import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KG network analysis panel', () => {
  it('connects all KG network analysis endpoints on the graph page surface', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-network-analysis-panel.tsx'), 'utf8')

    expect(src).toContain('kgApi.getKHopNeighbors')
    expect(src).toContain('kgApi.getShortestPath')
    expect(src).toContain('kgApi.getPathsBetween')
    expect(src).toContain('kgApi.getCentrality')
    expect(src).toContain('kgApi.getCommunityOf')
    expect(src).toContain('kgApi.getConnectedComponent')
  })
})
