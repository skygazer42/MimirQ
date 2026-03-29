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

  it('buffers the latest token in a fade layer before committing to markdown', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'cinematic-typewriter.tsx'), 'utf8')

    expect(src).toContain('const [pendingToken, setPendingToken] = useState("")')
    expect(src).toContain('const [pendingTokenKey, setPendingTokenKey] = useState(0)')
    expect(src).toContain('pendingRef.current = token')
    expect(src).toContain('setPendingToken(token)')
    expect(src).toContain('setPendingTokenKey((prev) => prev + 1)')
    expect(src).toContain("setPendingToken('')")
    expect(src).toContain('whitespace-pre-wrap')
    expect(src).toContain('animate-fade-in')
    expect(src).toContain("from 'framer-motion'")
    expect(src).toContain('useReducedMotion')
    expect(src).toContain('AnimatePresence')
    expect(src).toContain('mode="popLayout"')
    expect(src).toContain('motion.span')
  })
})
