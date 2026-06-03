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

    expect(src).toContain('flex min-h-[calc(100vh-11.5rem)] flex-col overflow-hidden rounded-3xl border border-border/60 bg-card/90 shadow-soft')
    expect(src).toContain('grid min-h-0 flex-1 gap-2.5')
    expect(src).toContain('section className="min-h-0 min-w-0"')
    expect(src).toContain('data-dataset-catalog-scroll="true"')
    expect(src).toContain('min-h-0 flex-1 overflow-y-auto overscroll-contain custom-scrollbar')
    expect(src).toContain('lg:grid-cols-[176px_minmax(0,1fr)]')
    expect(src).toContain('xl:grid-cols-[minmax(0,1.15fr)_320px]')
    expect(src).toContain('Dataset Inspector')
    expect(src).toContain('选择一个数据集以查看快捷入口与访问配置')
    expect(src).toContain('<DatasetShortcutButton')
  })

  it('loads the dataset collection through TanStack Query', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQuery')
    expect(src).toContain('useQueryClient')
    expect(src).toContain('queryKey: datasetsQueryKey')
    expect(src).toContain('queryKeys.datasets.list')
    expect(src).not.toContain('const [items, setItems]')
    expect(src).not.toContain('const [total, setTotal]')
    expect(src).not.toContain('setIsLoading')
    expect(src).not.toContain('const load = useCallback')
  })

  it('keeps primary dataset actions bound to theme tokens instead of the default ocean palette', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).not.toContain('border-blue-300/80 bg-blue-50/50')
    expect(src).not.toContain('ring-blue-200/70')
    expect(src).not.toContain('border-blue-200 bg-blue-100/80')
    expect(src).not.toContain('text-blue-600')
    expect(src).not.toContain('bg-blue-600')
    expect(src).not.toContain('hover:bg-blue-50')
    expect(src).toContain('border-primary/30 bg-primary/5')
    expect(src).toContain('text-primary')
    expect(src).toContain('bg-primary')
  })
})
