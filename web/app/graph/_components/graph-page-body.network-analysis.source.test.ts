import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph page KG network analysis integration', () => {
  it('mounts the network analysis panel in the graph canvas body', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-page-body.tsx'), 'utf8')

    expect(src).toContain("import { KgNetworkAnalysisPanel } from './kg-network-analysis-panel'")
    expect(src).toContain('<KgNetworkAnalysisPanel')
    expect(src).toContain('links={networkAnalysisLinks}')
  })
})
