import { describe, expect, it } from 'vitest'

import { documentApi } from './api-client'

describe('documentApi.health', () => {
  it('is exposed', () => {
    expect(typeof (documentApi as any).health).toBe('function')
  })
})
