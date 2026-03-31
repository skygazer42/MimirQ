import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph parser worker source', () => {
  it('exposes GraphML parsing through a dedicated worker API', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-parser.worker.ts'), 'utf8')

    expect(src).toContain("import { expose } from 'comlink'")
    expect(src).toContain("import { parseGraphML } from '@/lib/graph-parser'")
    expect(src).toContain('parseGraphML')
    expect(src).toContain('export type GraphParserWorkerApi = typeof api')
    expect(src).toContain('expose(api)')
  })
})
