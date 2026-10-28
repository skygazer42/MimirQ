import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('data governance functional icon', () => {
  it('keeps the existing governance vector master for the page title', () => {
    const panel = fs.readFileSync(path.resolve(__dirname, 'data-governance-panel.tsx'), 'utf8')
    const mapping = fs.readFileSync(path.resolve(__dirname, 'icons/page-icons.ts'), 'utf8')
    const svg = fs.readFileSync(path.resolve(__dirname, '../public/page-title-icons/data-governance.svg'), 'utf8')
    expect(panel).toContain('<DataGovernance className=')
    expect(mapping).toContain("'data-governance': DataGovernance")
    expect(svg).toContain('data-platform-icon="data-governance"')
    expect(svg).toContain('stroke="currentColor"')
    expect(svg).not.toContain('<image')
  })
})
