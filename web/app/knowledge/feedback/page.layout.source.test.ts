import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('feedback triage page layout', () => {
  it('uses a dense full-width board with inline list controls instead of a floating capsule toolbar', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceNotToContain(src, 'toolbar={')
    expectSourceNotToContain(
      src,
      'rounded-full p-1.5 max-w-4xl mx-auto md:mx-0'
    )
    expectSourceToContain(
      src,
      "const hasActiveFilters = searchTerm.trim().length > 0 || filterType !== 'all' || ratingFilter !== 'all'"
    )
    expectSourceToContain(
      src,
      'overflow-hidden rounded-2xl border border-border/60 bg-card shadow-soft'
    )
    expectSourceToContain(src, 'placeholder="搜索反馈 / 原因 / 标签 / 账号"')
    expectSourceToContain(src, '{hasActiveFilters ? (')
    expectSourceToContain(src, 'const listSummary = useMemo(() => {')
    expectSourceToContain(
      src,
      "{items.length ? '长反馈与答复摘要优先' : '当前暂无反馈'}"
    )
    expectSourceToContain(src, '用户反馈')
    expectSourceToContain(src, '模型答复摘要')
    expectSourceToContain(
      src,
      "title={filterType === 'all' ? '按类型筛选（当前：全部）'"
    )
    expectSourceToContain(
      src,
      "title={ratingFilter === 'all' ? '按星级筛选（当前：全部）'"
    )
    expectSourceToContain(
      src,
      "{filterType === 'all' ? '类型' : filterType === 'thumbs_up' ? '类型 · 点赞' : '类型 · 点踩'}"
    )
    expectSourceToContain(
      src,
      "{ratingFilter === 'all' ? '星级' : `星级 · ${ratingFilter} 星`}"
    )
  })
})
