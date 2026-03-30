import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('history page a11y', () => {
  it('does not use div role=button for conversation list items', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    // Use native <button> for keyboard + screen reader semantics.
    expect(src).not.toContain('role="button"')
    expect(src).not.toContain('tabIndex={0}')
  })
})
