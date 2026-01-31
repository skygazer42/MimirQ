import { describe, expect, it } from 'vitest'

import { pipelineApi } from './api-client'

describe('pipelineApi.governanceProfiles', () => {
  it('exposes resolved profile endpoint client', () => {
    expect(typeof (pipelineApi as any).getGovernanceProfileResolved).toBe('function')
  })
})

