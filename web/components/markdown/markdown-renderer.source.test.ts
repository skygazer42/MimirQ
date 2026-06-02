import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('markdown renderer source', () => {
  it('routes protected backend images through the auth image component instead of query tokens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'markdown-renderer.tsx'), 'utf8')

    expect(src).toContain('AuthImage')
    expect(src).toContain('sanitizeMarkdownHref')
    expect(src).toContain('resolveMarkdownImageSrc')
    expect(src).toContain('MarkdownRenderBoundary')
    expect(src).toContain('Markdown 内容渲染失败')
    expect(src).not.toContain('maybeAttachImageAuthToken')
    expect(src).not.toContain("searchParams.set('token'")
    expect(src).not.toContain("searchParams.set('access_token'")
  })

  it('renders heading children explicitly instead of self-closing heading tags', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'markdown-renderer.tsx'), 'utf8')

    for (const level of [1, 2, 3, 4, 5, 6]) {
      expect(src).toContain(`return <h${level} {...props}>{children}</h${level}>`)
      expect(src).not.toContain(`return <h${level} {...props} />`)
    }
  })
})
