import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion live velocity source', () => {
  it('persists the processing efficiency toggle and exposes it as an accessible pressed button', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'live-velocity.tsx'), 'utf8')

    expect(src).toContain('mimirq.ingestion.velocityUnit')
    expect(src).toContain('aria-pressed')
    expect(src).toContain('处理效率')
    expect(src).toContain('近 5 min 均值')
    expect(src).toContain('docs/min')
    expect(src).toContain('MB/s')
  })
})
