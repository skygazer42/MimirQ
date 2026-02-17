import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('workbench scroll containers', () => {
  it('exposes internal scroll containers for RouteScrollReset', () => {
    const paneSrc = fs.readFileSync(path.resolve(__dirname, 'workbench-pane.tsx'), 'utf8')
    expect(paneSrc).toContain('data-page-scroll-container="true"')

    const scaffoldSrc = fs.readFileSync(path.resolve(__dirname, 'workbench-scaffold.tsx'), 'utf8')
    expect(scaffoldSrc).toContain('<WorkbenchPane')
  })
})

