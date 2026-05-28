import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports page typography', () => {
  it('uses shared report typography roles instead of scattered small text styles', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('const REPORT_LABEL_CLASS')
    expect(src).toContain('const REPORT_VALUE_CLASS')
    expect(src).toContain('const REPORT_METRIC_VALUE_CLASS')
    expect(src).toContain('const REPORT_PANEL_TITLE_CLASS')
    expect(src).toContain('const REPORT_TABLE_HEADER_CLASS')
    expect(src).toContain('const REPORT_TABLE_ROW_CLASS')
    expect(src).toContain('tabular-nums')
    expect(src).not.toContain('mt-1 font-mono text-[22px]')
    expect(src).not.toContain('mb-4 text-[15px] font-semibold text-slate-900')
  })
})
