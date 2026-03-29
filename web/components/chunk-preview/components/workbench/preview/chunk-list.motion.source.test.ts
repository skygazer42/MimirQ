import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk list motion source', () => {
  it('animates flat/hierarchy surface switches with reduced-motion safety', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-list.tsx'), 'utf8')

    expect(src).toContain("from 'framer-motion'")
    expect(src).toContain('useReducedMotion')
    expect(src).toContain('AnimatePresence')
    expect(src).toContain('mode="wait"')
    expect(src).toContain('const listSurfaceKey = `chunk-list-surface:${viewMode}:${groupMode}`')
    expect(src).toContain('layout={!reduceMotion}')
    expect(src).toContain('transition={surfaceTransition}')
  })
})
