import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('feedback page source', () => {
  it('shows real feedback loop candidates from feedbackApi', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('feedbackApi.loopCandidates')
    expect(src).toContain('反哺候选')
    expect(src).toContain('HardNeg')
    expect(src).toContain('规则候选')
  })
})
