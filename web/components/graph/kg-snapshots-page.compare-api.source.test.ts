import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KG snapshots compareSnapshots productization', () => {
  it('uses the backend compareSnapshots endpoint as an explicit action', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-snapshots-page.tsx'), 'utf8')

    expect(src).toContain('kgApi.compareSnapshots')
    expect(src).toContain('后端对比')
  })
})
