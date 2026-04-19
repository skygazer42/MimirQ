import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Datasets default pipeline toggle', () => {
  it('renders a switch and persists the toggle via datasetApi.update', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')
    expect(src).toContain("import { Switch } from '@/components/ui/switch'")
    expect(src).toContain('handleToggleDefaultPipeline')
    expect(src).toContain('<Switch')
    expect(src).toContain('pipeline: nextEnabled ? mergePipelineOptions(defaultPipelineOptions, dataset.pipeline) : {}')
  })
})
