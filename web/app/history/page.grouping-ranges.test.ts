import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page conversation grouping ranges', () => {
  it('groups conversations into today, last 7 days, last 30 days, and earlier without a separate yesterday bucket', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('last7Days: t(\'groupLast7Days\')')
    expect(src).toContain('last30Days: t(\'groupLast30Days\')')
    expect(src).not.toContain('groupOrder = [\n    groupLabels.today,\n    groupLabels.yesterday,')
    expect(src).not.toContain('group = labels.yesterday')
    expect(src).toContain('lastMonth.setDate(lastMonth.getDate() - 30)')
  })
})
