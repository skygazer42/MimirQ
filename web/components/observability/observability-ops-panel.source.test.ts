import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ObservabilityOpsPanel source', () => {
  it('surfaces operational observability APIs outside diagnostics', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'observability-ops-panel.tsx'), 'utf8')

    for (const api of [
      'observabilityApi.getOnlineQualitySummary',
      'observabilityApi.getRagCostAttribution',
      'observabilityApi.getRagMetricsTail',
      'observabilityApi.getDepsDiagnosticsSnapshot',
      'observabilityApi.getPeriodicJobFreshness',
      'observabilityApi.getTaskQueueSnapshot',
      'observabilityApi.getSloSnapshot',
      'observabilityApi.getEmbeddingDriftSnapshot',
      'observabilityApi.runPerfSuite',
      'observabilityApi.invalidateDatasetCache',
      'observabilityApi.listIndexDrift',
      'observabilityApi.resolveIndexDrift',
    ]) {
      expect(src).toContain(api)
    }
  })
})
