import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('audit page bound filters', () => {
  it('derives selectable filter options from backend audit logs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(
      src,
      "import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'"
    )
    expectSourceToContain(src, 'AUDIT_FILTER_OPTION_PAGE_SIZE = 200')
    expectSourceToContain(src, 'AUDIT_FILTER_OPTION_MAX_PAGES')
    expectSourceToContain(
      src,
      'auditApi.listLogs({ skip: 0, limit: AUDIT_FILTER_OPTION_PAGE_SIZE })'
    )
    expectSourceToContain(
      src,
      'skip: pageIndex * AUDIT_FILTER_OPTION_PAGE_SIZE'
    )
    expectSourceToContain(src, 'function BoundFilterSelect')
    expectSourceToContain(src, 'options={actionOptions}')
    expectSourceToContain(src, 'options={actorOptions}')
    expectSourceToContain(src, 'options={requestOptions}')
    expectSourceToContain(src, 'options={resourceTypeOptions}')
    expectSourceToContain(src, 'options={resourceIdOptions}')
    expectSourceToContain(src, 'function formatAuditAction')
    expectSourceToContain(src, 'formatOption={formatAuditAction}')
    expectSourceToContain(src, 'formatOption={formatAuditResourceType}')
    expectSourceToContain(src, 'hover:bg-blue-50 hover:text-blue-700')
    expectSourceToContain(src, 'border-blue-600 bg-blue-600 text-white')
    expectSourceToContain(src, 'auditApi.deleteLog(id)')
    expectSourceToContain(src, 'auditApi.bulkDeleteLogs(ids)')
    expectSourceToContain(src, '删除已选 {selectedIds.length}')
    expectSourceToContain(src, 'aria-label="选择当前页审计日志"')
    expectSourceToContain(src, 'confirmLabel="删除"')
    expectSourceNotToContain(
      src,
      "placeholder={t('filters.actionPlaceholder')}"
    )
  })
})
