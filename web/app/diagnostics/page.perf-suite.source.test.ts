import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('/diagnostics perf suite', () => {
  it('includes perf suite probe UI', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain('runPerfSuite')
    expect(src).toContain('Perf Suite (API)')
    expect(src).toContain('/observability/perf-suite/run')
  })
})

