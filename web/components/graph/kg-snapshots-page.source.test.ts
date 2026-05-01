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
    expect(src).toContain('Snapshot Studio')
    expect(src).toContain('Hash A')
    expect(src).not.toContain('左右分屏对比')
  })

  it('keeps the left parameter sidebar and sticky compare actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-snapshots-page.tsx'), 'utf8')

    expect(src).toContain('对比参数')
    expect(src).toContain('作用范围')
    expect(src).toContain('导出 A')
    expect(src).toContain('导出 B')
    expect(src).toContain('开始对比')
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
