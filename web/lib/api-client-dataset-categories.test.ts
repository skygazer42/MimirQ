import { describe, expect, it } from 'vitest'

import { datasetApi, datasetCategoryApi } from './api-client'

describe('datasetCategoryApi', () => {
  it('is exposed', () => {
    expect(typeof (datasetCategoryApi as any).listTree).toBe('function')
  })
})

describe('datasetApi.categories', () => {
  it('is exposed', () => {
    expect(typeof (datasetApi as any).getCategories).toBe('function')
    expect(typeof (datasetApi as any).setCategories).toBe('function')
  })
})

