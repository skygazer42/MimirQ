import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('history page empty state', () => {
  it('offers a clear next action via the shared messages catalog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    const messages = fs.readFileSync(path.resolve(__dirname, '../../lib/messages.ts'), 'utf8')

    expect(src).toContain('uiMessages.history.startNewConversation')
    expect(messages).toContain("startNewConversation: '发起新对话'")
  })
})
