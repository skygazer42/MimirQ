import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('DocumentHealthPage source wiring', () => {
  it('loads the health card through the API client and renders the main sections', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-health-page.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.documents.health')
    expect(src).toContain('documentApi.health')
    expect(src).toContain('解析 → 分块 → KG → 检索命中')
    expect(src).toContain('ENABLE_METRICS_LOG=true')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setData(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('setError(')
    expect(src).not.toContain('detachPromise(load())')
  })

  it('keeps display formatting explicit and avoids nested ternaries in badges and retrieval status', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-health-page.tsx'), 'utf8')

    expect(src).not.toContain('return String(value)')
    expect(src).not.toContain("qualityBadge.tone === 'bad'")
    expect(src).not.toContain("data.retrieval_hits?.enabled ? (data.retrieval_hits.available ? 'available' : 'missing') : 'disabled'")
    expect(src).not.toContain('{!data.retrieval_hits?.enabled ? (')
  })
})
