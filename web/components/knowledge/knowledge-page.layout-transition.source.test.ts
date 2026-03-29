import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage layout transition', () => {
  it('uses framer-motion layout primitives with reduced-motion safety for documents view switching', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain("from 'framer-motion'")
    expect(src).toContain('useReducedMotion')
    expect(src).toContain('layout={!reduceMotion}')
    expect(src).toContain('layoutId="knowledge-view-mode-active-pill"')
    expect(src).toContain('layoutId="knowledge-documents-surface"')
  })
})
