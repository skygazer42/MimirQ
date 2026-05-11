import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('governance profiles page api error formatting', () => {
  it('uses formatApiError for backend failures (request_id included)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-profiles-page.tsx'), 'utf8')

    expect(src).toContain('formatApiError(')
    expect(src).not.toContain('err?.response?.data?.detail')
  })

  it('uses TanStack Query for profile list loading and write refreshes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-profiles-page.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.governance.profiles')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setResp(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('detachPromise(load())')
    expect(src).not.toContain('await pipelineApi.listGovernanceProfiles(params)')
  })
})
