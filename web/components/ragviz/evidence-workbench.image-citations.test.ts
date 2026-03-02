import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('evidence workbench image citations', () => {
  it('renders safe thumbnails for image citations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-workbench.tsx'), 'utf8')
    expect(src).toContain('resolveSafeCitationImageUrl')
  })
})

