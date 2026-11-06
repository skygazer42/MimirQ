import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('conversation ops panel source', () => {
  it('uses ruled boundaries instead of decorative gradients and glow', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'conversation-ops-panel.tsx'), 'utf8')

    expect(source).toContain('data-history-ops-panel="true"')
    expect(source).toContain('data-history-ops-boundary="ruled"')
    expect(source).toContain('variant="seamless"')
    expect(source).toContain('padding="none"')
    expect(source).not.toContain('linear-gradient')
    expect(source).not.toContain('blur-2xl')
    expect(source).not.toContain('shadow-[0_12px_36px')
  })
})
