import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('markdown source', () => {
  it('uses default parameters and regex exec helpers for heading extraction', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'markdown.ts'), 'utf8')

    expect(src).toContain("function stripInlineMarkdown(text = '')")
    expect(src).toContain('const fenceMatch = CODE_FENCE_RE.exec(trimmed)')
    expect(src).toContain('const headingMatch = MARKDOWN_HEADING_RE.exec(line)')
    expect(src).toContain('function parseMarkdownHeadingLine(')
    expect(src).not.toContain('trimmed.match(')
    expect(src).not.toContain('line.match(')
  })
})
