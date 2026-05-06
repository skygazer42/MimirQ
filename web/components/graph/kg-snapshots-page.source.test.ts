import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KG snapshots page layout', () => {
  it('uses an IDE-style tabs workspace with side-by-side diff by default', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-snapshots-page.tsx'), 'utf8')

    expect(src).toContain('Diff 对比')
    expect(src).toContain('视图 A')
    expect(src).toContain('视图 B')
    expect(src).toContain('buildSideBySideDiffRows')
    expect(src).toContain('快照工作台')
    expect(src).toContain('快照 A')
    expect(src).not.toContain('左右分屏对比')
  })

  it('keeps the left parameter sidebar and sticky compare actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-snapshots-page.tsx'), 'utf8')

    expect(src).toContain('对比参数')
    expect(src).toContain('流水线哈希')
    expect(src).toContain('快照 B')
    expect(src).toContain('作用范围')
    expect(src).toContain('文档范围')
    expect(src).toContain('label="文档"')
    expect(src).toContain('label="模式"')
    expect(src).toContain('导出 A')
    expect(src).toContain('导出 B')
    expect(src).toContain('开始对比')
  })

  it('keeps graph relation labels visually close to the design reference', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-snapshots-page.tsx'), 'utf8')

    expect(src).toContain('className="fill-slate-400 text-[1.55px] font-normal tracking-[0.03em]"')
    expect(src).not.toContain('text-[2.2px] font-medium')
  })

  it('renders the graph-studio canvas, toolbar, and node detail rail from the reference design', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-snapshots-page.tsx'), 'utf8')

    expect(src).toContain('SNAPSHOT_STUDIO_NODES')
    expect(src).toContain('SNAPSHOT_STUDIO_LINKS')
    expect(src).toContain('SnapshotGraphCanvas')
    expect(src).toContain('data-testid="kg-snapshot-graph-canvas"')
    expect(src).toContain('搜索节点 / 关系')
    expect(src).toContain('图谱视图')
    expect(src).toContain('表格视图')
    expect(src).toContain('统计视图')
    expect(src).toContain('节点详情')
    expect(src).toContain('关联关系 ({selectedNode.relations.length})')
    expect(src).toContain('Diff 概览')
  })

  it('surfaces exact node and edge drift instead of only JSON line diff', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-snapshots-page.tsx'), 'utf8')

    expect(src).toContain('SnapshotExactDriftPanel')
    expect(src).toContain('node_diff')
    expect(src).toContain('edge_diff')
    expect(src).toContain('精确节点/边 Diff')
    expect(src).toContain('include_details: true')
  })
})
