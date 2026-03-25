import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('EvidenceSuiteWorkbench guards', () => {
  it('uses a block body when query is empty before building snapshots', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-suite-workbench.tsx'), 'utf8')

    expect(src).toContain('if (!query) {')
    expect(src).toContain('return')
  })

  it('avoids any-based helpers and state in the evidence suite workbench', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-suite-workbench.tsx'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'suite-list-panel.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'item-list-panel.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'item-detail-panel.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'hardcase-candidates-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'suite-dashboard-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'create-item-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'why-missed-dialog.tsx'))).toBe(true)
    expect(src).toContain('SuiteListPanel')
    expect(src).toContain('ItemListPanel')
    expect(src).toContain('ItemDetailPanel')
    expect(src).toContain('HardcaseCandidatesDialog')
    expect(src).toContain('SuiteDashboardDialog')
    expect(src).toContain('CreateItemDialog')
    expect(src).toContain('WhyMissedDialog')
    expect(src).not.toContain(': any')
    expect(src).not.toContain('Record<string, any>')
  })
})
