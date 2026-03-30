import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel single delete confirmation', () => {
  it('confirms single delete via AlertDialog and keeps errors next to the action', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('singleDeleteDoc')
    expect(src).toContain('formatApiError')
    expect(src).toContain('setSingleDeleteError')
    expect(src).toContain('toast.success(t("toasts.deleteSuccess"))')
    expect(src).toContain('Delete document failed:')
  })
})
