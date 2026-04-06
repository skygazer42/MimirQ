import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('markdown source', () => {
  it('uses default parameters and extracted helpers for heading extraction', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'markdown.ts'), 'utf8')

    expect(src).toContain("function stripInlineMarkdown(text = '')")
    expect(src).toContain('function parseMarkdownHeadingLine(')
    expect(src).toContain('const fenceMatch = CODE_FENCE_RE.exec(trimmed)')
    expect(src).not.toContain('trimmed.match(')
    expect(src).not.toContain('line.match(')
    expect(src).not.toContain('MARKDOWN_HEADING_RE')
    expect(src).not.toContain('.exec(line)')
  })

  it('avoids hotspot-prone inline markdown replaceAll regexes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'markdown.ts'), 'utf8')

    expect(src).not.toContain("replaceAll(/!\\[([^\\]]*)\\]\\([^)]+\\)/g, '$1')")
    expect(src).not.toContain("replaceAll(/\\[([^\\]]+)\\]\\([^)]+\\)/g, '$1')")
    expect(src).not.toContain("replaceAll(/`([^`]+)`/g, '$1')")
    expect(src).not.toContain("replaceAll(/<[^>]+>/g, '')")
  })

  it('supports scrolling to headings within a named scroll container', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'markdown.ts'), 'utf8')

    expect(src).toContain('scrollContainerSelector?: string')
    expect(src).toContain('document.querySelector<HTMLElement>(containerSelector)')
    expect(src).toContain('container.scrollTo({')
  })
})
