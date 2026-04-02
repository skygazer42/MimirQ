import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing sonar source guards', () => {
  it('avoids object stringification and nested quality-gate ternaries in the active file pane', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('function readBackendName(')
    expect(src).toContain('function getQualityBadgeClass(')
    expect(src).toContain('const submitToGovernanceButton = isEditing ? null : (')
    expect(src).toContain("const ParseCompareDialog = dynamic(")
    expect(src).toContain("import('@/components/parsing/parse-compare-dialog')")
    expect(src).not.toContain("import { ParseCompareDialog } from '@/components/parsing/parse-compare-dialog'")
    expect(src).not.toContain("String(gateEvidence.fallback_initial_backend || '')")
    expect(src).toContain('fallbackBackends.join(')
    expect(src).toContain('getQualityBadgeClass(qualityGrade)')
  })

  it('extracts the pending parse action instead of nesting parse-button ternaries', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-library-preview-pane.tsx'), 'utf8')

    expect(src).toContain('const pendingParseAction = (() => {')
    expect(src).toContain("label: t('libraryPreview.continueParsing')")
    expect(src).toContain("label: t('libraryPreview.uploadAndParse')")
    expect(src).toContain('onClick={pendingParseAction.onClick}')
    expect(src).toContain('title={pendingParseAction.title}')
    expect(src).toContain('{pendingParseAction.label}')
  })
})
