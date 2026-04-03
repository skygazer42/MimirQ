import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('datasets page source', () => {
  it('avoids empty-object spreads and wraps adjacent description text explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).not.toContain('...(ds.pipeline || {})')
    expect(src).not.toContain('...(patch || {})')
    expect(src).toContain('<span>管理知识库集合与访问权限</span>')
  })

  it('uses a single datasets workbench container with a split collection-console layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('flex min-h-[calc(100vh-11.5rem)] flex-col overflow-hidden rounded-[1.75rem] border border-border/60 bg-card/90 shadow-soft')
    expect(src).toContain('lg:grid-cols-[176px_minmax(0,1fr)]')
    expect(src).toContain('xl:grid-cols-[minmax(0,1.15fr)_320px]')
    expect(src).toContain('数据集检视器')
    expect(src).toContain('选择一个数据集以查看快捷入口与访问配置')
    expect(src).toContain('<DatasetShortcutButton')
  })
})
