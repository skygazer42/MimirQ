import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage mobile queue dialog', () => {
  it('exposes the queue panel via WorkbenchPanelDialog on small screens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const shellSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'), 'utf8')
    const contentSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-mobile-queue-content.tsx'), 'utf8')
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-queue-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'))).toBe(true)

    expect(src).toContain('ParsingWorkbenchShell')
    expect(shellSrc).toContain('<WorkbenchPanelDialog')
    expect(shellSrc).toContain('open={queueOpen}')
    expect(shellSrc).toContain('onOpenChange={setQueueOpen}')
    expect(shellSrc).toContain("title={t('queue')}")
    expect(shellSrc).toContain('ParsingMobileQueueContent')
    expect(contentSrc).toContain("useTranslations('ParsingWorkbench')")
    expect(contentSrc).toContain("t('mobileQueue.title')")
    expect(contentSrc).toContain("t('mobileQueue.parseAll')")
    expect(contentSrc).toContain("t('mobileQueue.currentSession')")
    expect(contentSrc).toContain("t('mobileQueue.library')")
  })
})
