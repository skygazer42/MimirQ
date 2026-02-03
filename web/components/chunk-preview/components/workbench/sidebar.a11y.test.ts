import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('chunk preview sidebar a11y', () => {
  it('does not use div role=button for selectable file rows', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar.tsx'), 'utf8')

    // Prefer native <button> semantics for keyboard support and screen readers.
    expect(src).not.toContain('role="button"')
    expect(src).not.toContain('tabIndex={0}')
  })
})

