import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge feedback real-data mode', () => {
  it('keeps demo feedback data behind explicit demoMode gating', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toMatch(/demoMode\s*=\s*[\s\S]*pathname[\s\S]*demo/)
    expect(src).toContain("searchParams.get('demo') === '1'")
    expect(src).toContain('enabled: !demoMode')
    expect(src).toContain("() => (demoMode ? buildDemoFeedbackItems() : data?.items || [])")
    expect(src).toContain('if (demoMode) {')
    expect(src).toContain('if (demoMode) return demoMetrics.topReasons')
    expect(src).toContain('if (demoMode) return demoMetrics.sources')
    expect(src).toContain('if (demoMode) return demoMetrics.trend')
    expect(src).toContain("params.delete('demo')")
    expect(src).not.toContain("params.set('demo', '1')")
    expect(src).not.toContain('data?.items ?? buildDemoFeedbackItems')
    expect(src).not.toContain('loopCandidateData ?? demoMetrics')
    expect(src).not.toContain('const [archivedIds, setArchivedIds]')
    expect(src).not.toContain('toast.success(\'已更新处理状态\')')
    expect(src).toMatch(/feedbackApi\.(patch|update)/)
  })
})
