import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph page actions source', () => {
  it('routes node-to-chat actions through an autorun prompt handoff', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-graph-page-actions.ts'), 'utf8')

    expect(src).toContain('buildGraphNodeChatPrompt')
    expect(src).toContain("autorun: '1'")
    expect(src).toContain('router.push(`/?${params.toString()}`)')
  })
})
