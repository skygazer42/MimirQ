import { describe, expect, it } from 'vitest'

import { documentApi } from './api-client'

describe('documentApi.folders', () => {
  it('is exposed', () => {
    expect(typeof (documentApi as any).folders).toBe('function')
  })
})

