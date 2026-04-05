import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Datasets page header', () => {
  it('does not use decorative pulse animations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')
    expect(src).not.toContain('animate-pulse')
  })

  it('uses the dedicated create dataset CTA for the header action only', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')
    expect(src).toContain("import { CreateDatasetButton } from '@/components/datasets/create-dataset-button'")
    expect(src.match(/<CreateDatasetButton\b/g) ?? []).toHaveLength(1)
  })

  it('registers the create dataset CTA jello animation globally', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../globals.css'), 'utf8')
    expect(src).toContain('@keyframes dataset-jello-vertical')
  })
})
