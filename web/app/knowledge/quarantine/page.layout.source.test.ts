import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('quarantine queue page layout', () => {
  it('uses a compact dashboard header, inline queue filters, and a right-side review drawer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceNotToContain(src, 'toolbar={')
    expectSourceNotToContain(src, 'xl:grid-cols-[1.2fr_0.8fr]')
    expectSourceToContain(src, 'showHeader={false}')
    expectSourceToContain(src, '<PageHeader')
    expectSourceToContain(src, 'description="聚合命中规则，抽样预览原文，一键调参回放。这里集中处理被隔离的异常样本，帮助你快速完成复核和回放。"')
    expectSourceToContain(
      src,
      "const [selectedDataset, setSelectedDataset] = useState('all')"
    )
    expectSourceToContain(
      src,
      "const [reviewState, setReviewState] = useState<'all' | 'pending' | 'reviewed'>('all')"
    )
    expectSourceToContain(src, 'grid gap-2.5 md:grid-cols-2 xl:grid-cols-4')
    expectSourceToContain(src, 'placeholder="搜索文件名 / ID / 规则 / 原因"')
    expectSourceToContain(src, '规则集中率')
    expectSourceToContain(src, '较昨日')
    expectSourceToContain(src, 'max-w-[1520px]')
    expectSourceToContain(src, 'min-h-[104px]')
    expectSourceToContain(
      src,
      'bg-[radial-gradient(circle_at_top,rgba(37,99,235,0.10),transparent_34rem)'
    )
    expectSourceToContain(src, '规则命中分布 TOP5')
    expectSourceToContain(src, '快捷操作')
    expectSourceToContain(
      src,
      'left-auto right-0 top-0 h-dvh w-[min(520px,100vw)] max-w-[520px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden'
    )
    expectSourceToContain(src, 'const listSummary = useMemo(() => {')
    expectSourceToContain(src, '当前筛选条件下暂无隔离记录')
    expectSourceToContain(src, '当前没有待审隔离样本')
  })
})
