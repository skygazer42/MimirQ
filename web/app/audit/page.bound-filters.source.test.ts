import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('audit page bound filters', () => {
  it('derives selectable filter options from backend audit logs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'")
    expect(src).toContain('AUDIT_FILTER_OPTION_PAGE_SIZE = 200')
    expect(src).toContain('AUDIT_FILTER_OPTION_MAX_PAGES')
    expect(src).toContain('auditApi.listLogs({ skip: 0, limit: AUDIT_FILTER_OPTION_PAGE_SIZE })')
    expect(src).toContain('skip: pageIndex * AUDIT_FILTER_OPTION_PAGE_SIZE')
    expect(src).toContain('function BoundFilterSelect')
    expect(src).toContain("options={actionOptions}")
    expect(src).toContain("options={actorOptions}")
    expect(src).toContain("options={requestOptions}")
    expect(src).toContain("options={resourceTypeOptions}")
    expect(src).toContain("options={resourceIdOptions}")
    expect(src).not.toContain("placeholder={t('filters.actionPlaceholder')}")
  })
})
