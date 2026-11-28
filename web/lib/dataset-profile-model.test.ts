import { describe, expect, it } from 'vitest'

import { makeProfileSummary } from '../test/dataset-profile-fixtures'
import { buildDatasetProfileModel } from './dataset-profile-model'

describe('dataset profile status colors', () => {
  it.each([
    { completed: 4, failed: 2 },
    { failed: 2, completed: 4 },
  ])('keeps success and failure colors independent of response order', (by_status) => {
    const model = buildDatasetProfileModel(makeProfileSummary({ by_status }), ['cyan', 'green'])

    expect(model.statuses.find((row) => row.key === 'failed')).toMatchObject({
      value: 2,
      fill: 'hsl(var(--destructive))',
    })
    expect(model.statuses.find((row) => row.key === 'completed')).toMatchObject({
      value: 4,
      fill: 'hsl(var(--success))',
    })
  })

  it('keeps an unfamiliar status and its count visible with a neutral color', () => {
    const model = buildDatasetProfileModel(makeProfileSummary({ by_status: { importing: 3 } }), ['green'])

    expect(model.statuses).toEqual([
      { key: 'importing', name: 'importing', value: 3, fill: 'hsl(var(--muted-foreground))' },
    ])
  })
})
