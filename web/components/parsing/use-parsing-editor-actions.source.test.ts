import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('useParsingEditorActions source', () => {
  it('awaits parsed library updates when saving edited markdown', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-editor-actions.ts'), 'utf8')

    expect(src).toContain('await updateParsedFile(libId, {')
    expect(src).toContain("status: 'parsed'")
    expect(src).toContain("governanceStatus: 'ready'")
  })

  it('exposes a batch governance submit action for selected ready documents', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-editor-actions.ts'), 'utf8')

    expect(src).toContain('const handleSubmitSelectedToGovernance = useCallback(async () => {')
    expect(src).toContain('selectedGovernanceFileIds')
    expect(src).toContain("governanceStatus: 'submitted'")
    expect(src).toContain('setSelectedGovernanceFileIds(new Set())')
    expect(src).toContain('handleSubmitSelectedToGovernance')
  })
})
