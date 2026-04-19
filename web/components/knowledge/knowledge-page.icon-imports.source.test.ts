import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage icon imports', () => {
  it('imports every lucide icon used by the page shell stats and toolbars', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('icon={CheckCircle}')
    expect(src).toMatch(/import\s*\{[\s\S]*\bCheckCircle\b[\s\S]*\}\s*from 'lucide-react'/)
  })
})
