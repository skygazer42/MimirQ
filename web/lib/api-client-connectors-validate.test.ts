import { describe, expect, it } from 'vitest'

import { connectorApi } from './api-client'

describe('connectorApi.validateConfig', () => {
  it('is exposed', () => {
    expect(typeof (connectorApi as any).validateConfig).toBe('function')
  })
})

