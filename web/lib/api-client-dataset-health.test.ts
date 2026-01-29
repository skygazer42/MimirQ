import { describe, expect, it } from 'vitest'

import { datasetApi } from './api-client'

describe('datasetApi.getHealth', () => {
  it('is exposed', () => {
    expect(typeof (datasetApi as any).getHealth).toBe('function')
  })
})

