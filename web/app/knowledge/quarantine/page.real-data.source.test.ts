import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge quarantine real-data mode', () => {
  it('keeps demo quarantine documents behind explicit demoMode gating', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toMatch(/demoMode\s*=\s*[\s\S]*pathname[\s\S]*demo/)
    expect(src).toContain("searchParams.get('demo') === '1'")
    expect(src).toContain('enabled: !demoMode')
    expect(src).toMatch(
      /const\s+documents\s*=\s*useMemo\([\s\S]*demoMode[\s\S]*buildDemoQuarantineDocuments\(\)[\s\S]*data\?\.items[\s\S]*failedData\?\.items[\s\S]*\[data,\s*demoMode,\s*failedData\]/
    )
    expect(src).toContain("params.delete('demo')")
    expect(src).not.toContain("params.set('demo', '1')")
    expect(src).not.toContain('data?.items ?? buildDemoQuarantineDocuments')
  })
})
