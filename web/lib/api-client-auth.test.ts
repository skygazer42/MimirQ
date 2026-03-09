import { describe, expect, it } from 'vitest'

import { authApi } from './api-client'

describe('authApi', () => {
  it('exposes samlExchange', () => {
    expect(typeof (authApi as any).samlExchange).toBe('function')
  })
})
