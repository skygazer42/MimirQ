import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('queryset health tab query convergence', () => {
  it('uses TanStack Query for queryset health runs and diff loading', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'queryset-health-tab-client.tsx'),
      'utf8'
    )

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain('queryKey: queryKeys.evaluations.querysetHealthRuns({ limit: 90 })')
    expect(src).toContain('queryKey: queryKeys.evaluations.querysetHealthDiff({')
    expect(src).not.toContain('const loadRuns = useCallback(async () => {')
    expect(src).not.toContain('const loadDiff = useCallback(')
    expect(src).not.toContain('detachPromise(loadRuns())')
    expect(src).not.toContain('detachPromise(loadDiff({ baseline: baselineTs, current: currentTs }))')
  })
})
