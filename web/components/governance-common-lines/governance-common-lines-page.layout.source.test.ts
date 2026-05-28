import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('governance common lines layout source', () => {
  it('uses a dense pseudo-table header for candidates', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).toContain('重复行预览')
    expect(src).toContain('命中文档')
    expect(src).toContain('命中比例')
    expect(src).toContain('grid-cols-[44px_minmax(0,1fr)_110px_110px]')
  })

  it('removes the redundant checkbox field label', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).not.toContain('<Label>优先使用原始文本</Label>')
    expect(src).toContain('优先基于治理前的原始解析结果进行识别')
  })

  it('keeps the workbench full-width and uses a compact split layout instead of a distant centered stack', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).toContain('size="full"')
    expect(src).toContain('density="system-dense"')
    expect(src).not.toContain("mx-auto max-w-[1320px]")
    expect(src).toContain('xl:grid-cols-[420px_minmax(0,1fr)]')
    expect(src).toContain('xl:grid-cols-[0px_minmax(0,1fr)]')
    expect(src).toContain('min-h-[760px]')
    expect(src).toContain('rounded-2xl border border-border/60 bg-card shadow-subtle')
    expect(src).toContain('data-testid="common-lines-control-panel"')
  })

  it('combines the left rail sections into one collapsible control panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).toContain('识别范围')
    expect(src).toContain('目标')
    expect(src).toContain('参数')
    expect(src).toContain('common-lines-control-panel')
    expect(src).not.toContain('mt-4 rounded-2xl border border-border/60 bg-card shadow-subtle')
    expect(src).not.toContain('样板行参数')
    expect(src).not.toContain('重复行参数')
  })

  it('keeps the empty results panel close to the reference workflow canvas', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).toContain('候选结果')
    expect(src).toContain('暂无数据')
    expect(src).toContain('扫描文档')
    expect(src).toContain('聚合重复样行')
    expect(src).toContain('写入治理配置')
    expect(src).toContain('ArrowRight')
  })

  it('removes panel wrappers so the page reads like a flat workbench instead of stacked cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).not.toContain("import { Panel }")
    expect(src).not.toContain('<Panel')
  })
})
