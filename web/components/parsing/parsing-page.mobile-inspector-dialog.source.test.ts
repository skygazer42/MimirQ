import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage mobile inspector dialog', () => {
  it('exposes inspector/navigation helpers via WorkbenchPanelDialog on small screens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const shellSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'), 'utf8')
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-inspector-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'))).toBe(true)

    expect(src).toContain('ParsingWorkbenchShell')
    expect(shellSrc).toContain('<WorkbenchPanelDialog')
    expect(shellSrc).toContain('open={inspectorOpen}')
    expect(shellSrc).toContain('onOpenChange={setInspectorOpen}')
    expect(shellSrc).toContain('title="工具"')
    expect(shellSrc).toContain('ParsingMobileInspectorContent')
  })
})
