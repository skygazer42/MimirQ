import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph display filters source', () => {
  it('reports expensive graph projections to frontend trace telemetry', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-graph-display-filters.ts'), 'utf8')

    expect(src).toContain("import('@/lib/frontend-trace')")
    expect(src).toContain('reportFrontendTrace(')
    expect(src).toContain("event: 'graph_render_projection'")
    expect(src).toContain('duration_ms:')
    expect(src).toContain('input_node_count:')
    expect(src).toContain('output_node_count:')
    expect(src).toContain('active_filter_count:')
  })
})
