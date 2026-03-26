import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage mobile inspector dialog', () => {
  it('exposes inspector/navigation helpers via WorkbenchPanelDialog on small screens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-inspector-content.tsx'))).toBe(true)

    expect(src).toContain('<WorkbenchPanelDialog')
    expect(src).toContain('open={inspectorOpen}')
    expect(src).toContain('onOpenChange={setInspectorOpen}')
    expect(src).toContain('title="工具"')
    expect(src).toContain('ParsingMobileInspectorContent')
  })
})
