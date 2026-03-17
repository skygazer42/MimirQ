import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset kg workbench route entry', () => {
  it('keeps app/datasets/[id]/kg/page.tsx as a thin wrapper (module boundary)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain('@/components/datasets/dataset-kg-workbench-page')
  })
})

