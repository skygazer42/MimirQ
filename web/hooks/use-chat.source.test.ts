import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('use-chat source', () => {
  it('delegates session, streaming, and formatting concerns to extracted modules', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-chat.ts'), 'utf8')
    const lineCount = src.split('\n').length

    expect(src).toContain("from './use-chat-session'")
    expect(src).toContain("from './use-chat-stream'")
    expect(src).toContain("from './use-chat-formatter'")
    expect(src).toContain('const session = useChatSession(')
    expect(src).toContain('const stream = useChatStream(')
    expect(lineCount).toBeLessThanOrEqual(220)
  })

  it.each([
    'use-chat-session.ts',
    'use-chat-stream.ts',
    'use-chat-formatter.ts',
  ])('keeps %s alongside the main hook', (fileName) => {
    const absolutePath = path.resolve(__dirname, fileName)

    expect(fs.existsSync(absolutePath)).toBe(true)
  })
})
