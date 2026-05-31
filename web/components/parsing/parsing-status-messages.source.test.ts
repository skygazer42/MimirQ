import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('parsing residual message sources', () => {
  it('moves left panel collapse/expand copy into ParsingWorkbench translations', () => {
    const src = read('./parsing-left-panel.tsx')

    expect(src).toContain("useTranslations('ParsingWorkbench')")
    expect(src).toContain("t('leftPanel.expandSidebar')")
    expect(src).toContain("t('leftPanel.collapseSidebar')")
  })

  it('moves library status labels behind translation lookups', () => {
    const utilsSrc = read('./parsing-page-utils.ts')
    const shellSrc = read('./parsing-workbench-shell.tsx')

    expect(utilsSrc).toContain('type ParsingWorkbenchTranslationGetter =')
    expect(utilsSrc).toContain("label: t('libraryStatus.parsed')")
    expect(utilsSrc).toContain("label: t('libraryStatus.parsing')")
    expect(utilsSrc).toContain("label: t('libraryStatus.error')")
    expect(utilsSrc).toContain("label: t('libraryStatus.pending')")
    expect(shellSrc).toContain('getLibraryStatusBadge(t, activeLibraryFile.status)')
  })

  it('moves queue/editor/run action toast copy into ParsingWorkbench translations', () => {
    const queueSrc = read('./use-parsing-queue-actions.ts')
    const editorSrc = read('./use-parsing-editor-actions.ts')
    const runSrc = read('./use-parsing-run-actions.ts')

    expect(queueSrc).toContain("useTranslations('ParsingWorkbench')")
    expect(queueSrc).toContain("t('toasts.deleteFailed')")
    expect(queueSrc).toContain("t('toasts.folderMoved')")
    expect(queueSrc).toContain("t('toasts.folderMoveInvalid')")

    expect(editorSrc).toContain("useTranslations('ParsingWorkbench')")
    expect(editorSrc).toContain("t('toasts.saveSuccess')")
    expect(editorSrc).toContain("t('toasts.saveFailed')")

    expect(runSrc).toContain("useTranslations('ParsingWorkbench')")
    expect(runSrc).toContain("t('toasts.parseFailed')")
  })
})
