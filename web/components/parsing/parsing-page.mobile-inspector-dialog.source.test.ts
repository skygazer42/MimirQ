import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage mobile inspector dialog', () => {
  it('exposes inspector/navigation helpers via WorkbenchPanelDialog on small screens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const shellSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'), 'utf8')
    const contentSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-mobile-inspector-content.tsx'), 'utf8')
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-inspector-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'))).toBe(true)

    expect(src).toContain('ParsingWorkbenchShell')
    expect(shellSrc).toContain('<WorkbenchPanelDialog')
    expect(shellSrc).toContain('open={inspectorOpen}')
    expect(shellSrc).toContain('onOpenChange={setInspectorOpen}')
    expect(shellSrc).toContain("title={t('tools')}")
    expect(shellSrc).toContain('ParsingMobileInspectorContent')
    expect(contentSrc).toContain("useTranslations('ParsingWorkbench')")
    expect(contentSrc).toContain("t('mobileInspector.view')")
    expect(contentSrc).toContain("t('mobileInspector.layout')")
    expect(contentSrc).toContain("t('mobileInspector.preview')")
    expect(contentSrc).toContain("t('mobileInspector.source')")
    expect(contentSrc).toContain("t('mobileInspector.blocks')")
    expect(contentSrc).toContain("t('mobileInspector.blockLabel'")
    expect(contentSrc).toContain("t('mobileInspector.pageLabel'")
    expect(contentSrc).toContain("t('mobileInspector.toc')")
    expect(contentSrc).toContain("t('mobileInspector.quickActions')")
    expect(contentSrc).toContain("t('mobileInspector.copyMarkdown')")
    expect(contentSrc).toContain("t('mobileInspector.downloadMarkdown')")
  })
})
