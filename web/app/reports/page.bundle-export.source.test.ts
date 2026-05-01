import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports page bundle export', () => {
  it('surfaces dataset report bundle zip export', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('reportApi.exportDatasetReportBundleZip')
    expect(src).toContain('导出 Bundle ZIP')
  })
})
