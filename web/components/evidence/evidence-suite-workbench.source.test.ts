import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('EvidenceSuiteWorkbench guards', () => {
  it('uses a block body when query is empty before building snapshots', () => {
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-evidence-suite-workbench-state.ts'), 'utf8')

    expect(hookSrc).toContain('if (!query) {')
    expect(hookSrc).toContain('return')
  })

  it('extracts shell and state helpers without any-based workbench source', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-suite-workbench.tsx'), 'utf8')
    const shellSrc = fs.readFileSync(path.resolve(__dirname, 'evidence-suite-workbench-shell.tsx'), 'utf8')
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-evidence-suite-workbench-state.ts'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'suite-list-panel.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'item-list-panel.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'item-detail-panel.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'hardcase-candidates-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'suite-dashboard-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'create-item-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'why-missed-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'evidence-suite-workbench-shell.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-evidence-suite-workbench-state.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'evidence-suite-workbench-utils.ts'))).toBe(true)
    expect(src).toContain('useEvidenceSuiteWorkbenchState')
    expect(src).toContain('EvidenceSuiteWorkbenchShell')
    expect(src).not.toContain('SuiteListPanel')
    expect(src).not.toContain('ItemListPanel')
    expect(src).not.toContain('ItemDetailPanel')
    expect(src).not.toContain('HardcaseCandidatesDialog')
    expect(src).not.toContain('SuiteDashboardDialog')
    expect(src).not.toContain('CreateItemDialog')
    expect(src).not.toContain('WhyMissedDialog')
    expect(shellSrc).toContain('SuiteListPanel')
    expect(shellSrc).toContain('ItemListPanel')
    expect(shellSrc).toContain('ItemDetailPanel')
    expect(shellSrc).toContain('HardcaseCandidatesDialog')
    expect(shellSrc).toContain('SuiteDashboardDialog')
    expect(shellSrc).toContain('CreateItemDialog')
    expect(shellSrc).toContain('WhyMissedDialog')
    expect(src).not.toContain(': any')
    expect(src).not.toContain('Record<string, any>')
    expect(hookSrc).not.toContain(': any')
    expect(hookSrc).not.toContain('Record<string, any>')
  })

  it('bridges pending feedback imports into the current suite workbench', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-suite-workbench.tsx'), 'utf8')
    const shellSrc = fs.readFileSync(path.resolve(__dirname, 'evidence-suite-workbench-shell.tsx'), 'utf8')
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-evidence-suite-workbench-state.ts'), 'utf8')

    expect(src).toContain('initialFeedbackId')
    expect(shellSrc).toContain('导入待处理反馈')
    expect(shellSrc).toContain('feedback_id')
    expect(hookSrc).toContain('pendingFeedbackId')
    expect(hookSrc).toContain('setPendingFeedbackId')
  })
})
