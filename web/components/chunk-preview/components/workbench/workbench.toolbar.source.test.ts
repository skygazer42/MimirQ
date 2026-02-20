import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview workbench toolbar', () => {
  it('mounts controls via WorkbenchScaffold toolbar (no ad-hoc top bar chrome)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).toContain('WorkbenchScaffold')
    expect(src).toContain('toolbar={toolbar}')

    expect(src).not.toContain('{/* 顶部栏 */}')
    expect(src).not.toContain('px-4 py-3 border-b border-border/60 bg-background/70')
  })
})

