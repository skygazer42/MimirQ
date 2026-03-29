import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('api-client Sonar guards', () => {
  it('keeps observability perf-suite defaults on integer literals', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api/observability.ts'), 'utf8')

    expect(src).toContain('timeout_sec: payload.timeout_sec ?? 2,')
    expect(src).not.toContain('timeout_sec: payload.timeout_sec ?? 2.0,')
  })
})
