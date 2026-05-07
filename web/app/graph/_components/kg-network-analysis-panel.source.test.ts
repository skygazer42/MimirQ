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

  it('keeps graph statistics visible before opening network analysis actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-network-analysis-panel.tsx'), 'utf8')

    expect(src).toContain('统计信息')
    expect(src).toContain('筛选器控制')
    expect(src).toContain('选中单元')
    expect(src).toContain('MetricRow')
  })

  it('allows the right-side graph statistics panel to collapse when it blocks the canvas', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-network-analysis-panel.tsx'), 'utf8')

    expect(src).toContain('const [collapsed, setCollapsed] = useState(false)')
    expect(src).toContain('aria-label="收起图谱统计栏"')
    expect(src).toContain('aria-label="展开图谱统计栏"')
    expect(src).toContain('id="kg-network-analysis-panel"')
    expect(src).toContain('right-[6.75rem]')
  })
})
