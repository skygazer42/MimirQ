import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('governance common lines layout source', () => {
  it('uses a dense pseudo-table header for candidates', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).toContain('样板行预览')
    expect(src).toContain('命中文档')
    expect(src).toContain('命中比例')
    expect(src).toContain('grid-cols-[30px_minmax(0,1fr)_76px_76px]')
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
    expect(src).toContain('xl:grid-cols-[320px_minmax(0,1fr)]')
    expect(src).toContain('xl:divide-x xl:divide-border/60')
  })

  it('removes panel wrappers so the page reads like a flat workbench instead of stacked cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')

    expect(src).not.toContain("import { Panel }")
    expect(src).not.toContain('<Panel')
  })
})
