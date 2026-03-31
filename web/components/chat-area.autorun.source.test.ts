import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chat area autorun source', () => {
  it('can auto-send prompt handoffs from command menu routes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('initialAutoSendPrompt')
    expect(src).toContain('autoSendPromptRef')
    expect(src).toContain('sendMessage(p)')
  })

  it('scopes chat requests to the currently opened document when the viewer is active', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain("useDocumentView((state) => state.documentId)")
    expect(src).toContain('documentIds: activeDocumentIds')
  })
})
