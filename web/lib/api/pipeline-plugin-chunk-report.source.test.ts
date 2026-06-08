import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('pipeline plugin chunk report API client source', () => {
  it('posts registered plugin sample requests to the chunk-report endpoint', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pipeline.ts'), 'utf8')

    expect(src).toContain('export type PipelinePluginChunkReportRequest')
    expect(src).toContain('export type PipelinePluginChunkReportResponse')
    expect(src).toContain('async buildPluginChunkReport(')
    expect(src).toContain("apiClient.post('/pipeline/plugins/chunk-report', payload)")
    expect(src).toContain('normalizePipelinePluginChunkReport')
    expect(src).toContain('readiness: isRecord(raw.readiness) ? raw.readiness')
    expect(src).toContain('sections: Array.isArray')
  })
})
