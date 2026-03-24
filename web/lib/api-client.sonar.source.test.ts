import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('api-client Sonar guards', () => {
  it('keeps type imports merged and avoids zero-fraction literals', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api-client.ts'), 'utf8')

    expect(src.match(/from '@\/types'/g) ?? []).toHaveLength(1)
    expect(src).toContain('timeout_sec: payload.timeout_sec ?? 2,')
    expect(src).not.toContain('timeout_sec: payload.timeout_sec ?? 2.0,')
  })
})
