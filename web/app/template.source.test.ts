import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('app template source', () => {
  it('scopes pipeline providers above pipeline routes without putting them back in root layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'template.tsx'), 'utf8')
    const routeScope = fs.readFileSync(
      path.resolve(__dirname, '../lib/pipeline-route-scope.ts'),
      'utf8'
    )

    expect(src).toContain('PipelineProviders')
    expect(src).toContain('usePathname')
    expect(src).toContain('needsPipelineProvidersForPathname')
    expect(src).toContain('@/lib/pipeline-route-scope')
    expect(routeScope).toContain('normalizePipelinePathname')
    expect(routeScope).toContain('segments.slice(1).join')
    expect(routeScope).toContain("'/datasets'")
    expect(routeScope).toContain("'/knowledge'")
    expect(routeScope).toContain("'/parsing'")
    expect(routeScope).toContain("'/chunk-preview'")
    expect(routeScope).toContain("'/settings'")
    expect(routeScope).toContain("'/data-governance'")
  })
})
