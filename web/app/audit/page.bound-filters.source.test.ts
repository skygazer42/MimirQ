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
    expectSourceNotToContain(
      src,
      "placeholder={t('filters.actionPlaceholder')}"
    )
  })
})
