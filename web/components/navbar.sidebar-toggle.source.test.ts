import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('navbar collapsed sidebar toggle', () => {
  it('keeps the collapsed-state toggle hidden behind an edge trigger and avoids forced focus reveal', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain('restoreToggleFocusOnCloseRef')
    expect(src).toContain('group/sidebar-toggle')
    expect(src).toContain('md:-translate-x-[110%] md:scale-95 md:opacity-0 md:pointer-events-none')
    expect(src).toContain('md:group-hover/sidebar-toggle:translate-x-2')
    expect(src).toContain('if (!shouldRestore || !shouldRestoreToggleFocus) return')
  })
})
