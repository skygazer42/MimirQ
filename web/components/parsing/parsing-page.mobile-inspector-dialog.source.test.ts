import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage mobile inspector dialog', () => {
  it('exposes inspector/navigation helpers via WorkbenchPanelDialog on small screens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')

    expect(src).toContain('<WorkbenchPanelDialog')
    expect(src).toContain('open={inspectorOpen}')
    expect(src).toContain('onOpenChange={setInspectorOpen}')
    expect(src).toContain('title="工具"')
  })
})

