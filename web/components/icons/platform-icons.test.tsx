import fs from 'node:fs'
import path from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import * as glyphs from './index'
import type { PlatformIcon } from './index'

const root = path.resolve(__dirname, '../..')
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'public/icons/ragvia/manifest.json'), 'utf8')) as {
  icons: { name: string; aliases: string[]; file: string }[]
}

describe('Ragvia functional icon family', () => {
  it('ships a renderable component and self-contained vector for every master and alias', () => {
    const exports = glyphs as Record<string, PlatformIcon>
    for (const entry of manifest.icons) {
      const svg = fs.readFileSync(path.join(root, 'public/icons/ragvia', entry.file), 'utf8')
      expect(svg, entry.name).toContain('viewBox="0 0 24 24"')
      expect(svg, entry.name).toContain('stroke="currentColor"')
      expect(svg, entry.name).not.toMatch(/<(?:image|script|foreignObject)\b|(?:href|src)=/)
      for (const name of [entry.name, ...entry.aliases]) {
        const markup = renderToStaticMarkup(createElement(exports[name]))
        expect(markup, name).toContain('data-platform-icon=')
        expect(markup, name).toContain('aria-hidden="true"')
        expect(markup, name).toContain('stroke-width="1.7"')
      }
    }
  })

  it('preserves named graphics, dimensions, stroke and SVG props for existing controls', () => {
    const named = renderToStaticMarkup(createElement(glyphs.Retrieval, {
      size: 20, strokeWidth: 2, absoluteStrokeWidth: true,
      className: 'text-primary', 'aria-label': '检索资料', 'data-testid': 'retrieval',
    } as React.ComponentProps<typeof glyphs.Retrieval>))
    expect(named).toContain('role="img"')
    expect(named).toContain('aria-label="检索资料"')
    expect(named).not.toContain('aria-hidden')
    expect(named).toContain('width="20"')
    expect(named).toContain('stroke-width="2.4"')
    expect(named).toContain('text-primary')
    expect(named).toContain('data-testid="retrieval"')
  })

  it('keeps production UI on the shared family without legacy raster marks or library imports', () => {
    const forbidden = /from\s+['"]lucide-react['"]|\/brand\/mimirq-[^'"\s]+\.png|\/page-title-icons\/[^'"\s]+\.png/
    for (const directory of ['app', 'components', 'lib', 'hooks']) {
      for (const file of fs.readdirSync(path.join(root, directory), { recursive: true }) as string[]) {
        if (!/\.[tj]sx?$/.test(file) || /\.test\./.test(file)) continue
        const source = fs.readFileSync(path.join(root, directory, file), 'utf8')
        expect(source, `${directory}/${file}`).not.toMatch(forbidden)
      }
    }
  })
})
