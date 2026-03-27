import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('cinematic typewriter source', () => {
  it('lazy-loads syntax highlighting instead of pulling it into the initial bundle', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'cinematic-typewriter.tsx'), 'utf8')

    expect(src).toContain("from 'next/dynamic'")
    expect(src).toContain('dynamic(')
    expect(src).toContain('sanitizeMarkdownHref')
    expect(src).toContain('resolveMarkdownImageSrc')
    expect(src).toContain('skipHtml')
    expect(src).not.toContain("import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'")
    expect(src).not.toContain("import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'")
  })
})
