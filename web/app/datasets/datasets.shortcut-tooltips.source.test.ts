import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Datasets shortcut descriptions', () => {
  it('preserves compact truncation while exposing the full description on hover', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')
    expect(src).toContain('leading-relaxed truncate')
    expect(src).toContain('title={description}')
  })
})
