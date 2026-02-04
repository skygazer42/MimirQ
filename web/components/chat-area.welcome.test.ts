import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('chat-area welcome screen', () => {
  it('does not render redundant "开始提问" CTA (composer is already the primary affordance)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')
    expect(src).not.toContain('开始提问')
  })
})
