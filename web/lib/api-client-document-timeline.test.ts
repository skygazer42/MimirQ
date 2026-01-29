import { describe, expect, it } from 'vitest'

import { documentApi } from './api-client'

describe('documentApi.getTimeline', () => {
  it('is exposed', () => {
    expect(typeof (documentApi as any).getTimeline).toBe('function')
  })
})

