import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph data loading source', () => {
  it('moves GraphML file parsing into a worker-backed pipeline with explicit main-thread fallback', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-graph-data-loading.ts'), 'utf8')

    expect(src).toContain("new URL('../../workers/graph-parser.worker.ts', import.meta.url)")
    expect(src).toContain('wrap<GraphParserWorkerApi>')
    expect(src).toContain('graphParserWorkerDisabledRef.current = true')
    expect(src).toContain("console.warn('Graph parser worker failed; falling back to main-thread parse', error)")
    expect(src).toContain('graphParserWorkerRef.current?.terminate()')
    expect(src).toContain('reader.onload = async (loadEvent) => {')
    expect(src).toContain('const parsedData = await parseGraphFileContent(content)')
  })
})
