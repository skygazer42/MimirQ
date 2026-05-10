import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph data loading source', () => {
  it('opens the unscoped graph page with live backend KG data instead of sample data', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-graph-data-loading.ts'), 'utf8')

    expect(src).toContain("const [autoLoadedGraphKey, setAutoLoadedGraphKey] = useState<string | null>(null)")
    expect(src).toContain("'default-live'")
    expect(src).toContain("void loadInitialData('live')")
    expect(src).not.toContain("scope.hasScope ? 'live' : 'mock'")
    expect(src).not.toContain("'default-mock-3d'")
    expect(src).not.toContain("source === 'mock'")
    expect(src).not.toContain('preferMock')
    expect(src).not.toContain('示例数据')
    expect(src).toContain("setViewMode('3d')")
  })

  it('checks backend KG availability before loading KG stats', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-graph-data-loading.ts'), 'utf8')

    expect(src).toContain("import { metaApi } from '@/lib/api'")
    expect(src).toContain('const meta = await metaApi.get()')
    expect(src).toContain('if (meta.features?.kg_enabled === false)')
    expect(src).toContain('setKgStats(null)')
  })

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
