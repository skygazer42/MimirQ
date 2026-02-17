import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('useKnowledgeScrollContainer', () => {
  it('resolves the main pane scroll element via closest() (no global selector)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-knowledge-scroll-container.ts'), 'utf8')

    expect(src).toContain('export function useKnowledgeScrollContainer')
    expect(src).toContain('closest<HTMLElement>(\'[data-page-scroll-container="true"]\')')
    expect(src).not.toContain('document.querySelector')
  })
})

