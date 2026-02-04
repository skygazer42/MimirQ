import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('history page empty state', () => {
  it('offers a clear next action when there is no conversation selected', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    // Baseline UI: empty states should guide users with one clear next action.
    expect(src).toContain('发起新对话')
  })
})

