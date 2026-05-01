import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('governance RTBF integration', () => {
  it('mounts RTBF request/status controls in data governance settings', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-section.tsx'), 'utf8')

    expect(src).toContain('rtbfApi.request')
    expect(src).toContain('rtbfApi.getStatus')
    expect(src).toContain('subject_account_id')
  })
})
