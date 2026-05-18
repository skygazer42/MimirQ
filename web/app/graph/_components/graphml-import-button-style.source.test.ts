import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (file: string) => fs.readFileSync(path.resolve(__dirname, file), 'utf8')

describe('GraphML import button style', () => {
  it('keeps GraphML import hover states readable across graph entry points', () => {
    const styles = read('graph-button-styles.ts')
    const header = read('graph-page-header.tsx')
    const canvas = read('graph-canvas.tsx')
    const scopePicker = read('graph-scope-picker-dialog.tsx')

    expect(styles).toContain('graphmlImportButtonClass')
    expect(styles).toContain('hover:bg-primary/10')
    expect(styles).toContain('hover:text-primary')
    expect(header).toContain('graphmlImportButtonClass')
    expect(canvas).toContain('graphmlImportButtonClass')
    expect(scopePicker).toContain('graphmlImportButtonClass')
  })
})
