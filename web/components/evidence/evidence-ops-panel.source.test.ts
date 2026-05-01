import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('EvidenceOpsPanel source', () => {
  it('surfaces drift, repair, training export and capsule APIs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-ops-panel.tsx'), 'utf8')

    for (const api of [
      'evidenceApi.getDatasetDriftAudit',
      'evidenceApi.repairSuiteReferenceSources',
      'evidenceApi.patchSuite',
      'evidenceApi.patchItem',
      'evidenceApi.exportTrainingDataset',
      'evidenceApi.persistCapsule',
      'evidenceApi.getCapsule',
      'evidenceApi.verifyCapsule',
    ]) {
      expect(src).toContain(api)
    }
  })
})
