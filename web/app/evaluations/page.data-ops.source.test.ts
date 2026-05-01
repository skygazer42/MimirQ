import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('evaluations page data operations', () => {
  it('mounts regression dataset operations explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { EvaluationDataOpsPanel } from '@/components/evaluation/evaluation-data-ops-panel'")
    expect(src).toContain('<EvaluationDataOpsPanel')
  })
})
