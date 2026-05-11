import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('audit page table pagination', () => {
  it('keeps audit columns and page controls in the table block', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src, '时间</th>')
    expectSourceToContain(src, '操作者</th>')
    expectSourceToContain(src, '事件名称</th>')
    expectSourceToContain(src, '资源 / 租户</th>')
    expectSourceToContain(src, '操作</th>')
    expectSourceToContain(src, '第 {displayPage} / {totalPages} 页')
    expectSourceToContain(
      src,
      'onClick={() => setSkip(Math.max(0, skip - limit))}'
    )
    expectSourceToContain(
      src,
      'onClick={() => setSkip(Math.min(Math.max(0, (totalPages - 1) * limit), skip + limit))}'
    )
    expectSourceToContain(
      src,
      'AUDIT_PAGE_SIZE_OPTIONS = [20, 50, 100] as const'
    )
    expectSourceToContain(src, 'max-h-[640px] overflow-auto')
    expectSourceToContain(src, 'onValueChange={handlePageSizeChange}')
  })

  it('shows tenant context in the resource column', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(
      src,
      '租户 <span className="font-mono">{log.tenant_id || \'-\'}</span>'
    )
    expectSourceToContain(
      src,
      'const timestamp = formatAuditDateTime(log.created_at)'
    )
  })
})
