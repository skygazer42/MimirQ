import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (file: string) => fs.readFileSync(path.resolve(__dirname, file), 'utf8')

describe('GraphML import button style', () => {
  it('keeps GraphML import removed from graph entry points', () => {
    const header = read('graph-page-header.tsx')
    const canvas = read('graph-canvas.tsx')
    const scopePicker = read('graph-scope-picker-dialog.tsx')

    expect(header).not.toContain('graphmlImportButtonClass')
    expect(header).not.toContain('accept=".graphml,.xml"')
    expect(header).not.toContain('GraphML 兼容')
    expect(canvas).not.toContain('graphmlImportButtonClass')
    expect(canvas).not.toContain('GraphML 兼容')
    expect(scopePicker).not.toContain('graphmlImportButtonClass')
    expect(scopePicker).not.toContain('GraphML 兼容')
  })
})
