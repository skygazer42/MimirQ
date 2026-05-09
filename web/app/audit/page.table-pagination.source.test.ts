import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('audit page table pagination', () => {
  it('keeps audit columns and page controls in the table block', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('时间</th>')
    expect(src).toContain('操作者</th>')
    expect(src).toContain('事件名称</th>')
    expect(src).toContain('资源 / 租户</th>')
    expect(src).toContain('操作</th>')
    expect(src).toContain('第 {displayPage} / {totalPages} 页')
    expect(src).toContain('onClick={() => setSkip(Math.max(0, skip - limit))}')
    expect(src).toContain('onClick={() => setSkip(Math.min(Math.max(0, (totalPages - 1) * limit), skip + limit))}')
    expect(src).toContain('AUDIT_PAGE_SIZE_OPTIONS = [20, 50, 100] as const')
    expect(src).toContain('max-h-[640px] overflow-auto')
    expect(src).toContain('onValueChange={handlePageSizeChange}')
  })

  it('shows tenant context in the resource column', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("租户 <span className=\"font-mono\">{log.tenant_id || '-'}</span>")
    expect(src).toContain("const timestamp = formatAuditDateTime(log.created_at)")
  })
})
