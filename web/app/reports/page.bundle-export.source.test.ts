// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports page bundle export', () => {
  it('surfaces dataset report bundle zip export', () => {
    // The bundle ZIP export handler wires the reportApi call in the page client.
    const pageClientSrc = fs.readFileSync(
      path.resolve(__dirname, 'page-client.tsx'),
      'utf8'
    )
    // The export menu item (with its aria-label copy) lives in the control panel component.
    const controlPanelSrc = fs.readFileSync(
      path.resolve(__dirname, 'components/reports-control-panel.tsx'),
      'utf8'
    )

    expect(pageClientSrc).toContain('reportApi.exportDatasetReportBundleZip')
    expect(controlPanelSrc).toContain('导出数据包 ZIP')
  })
})
