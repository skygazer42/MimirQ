import fs from 'node:fs'
import path from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { PAGE_TITLE_ICON_NAMES, PageTitleIcon } from './page-title-icon'

describe('PageTitleIcon vector coverage', () => {
  it('renders every existing title name as a decorative, theme-colored vector', () => {
    expect(PAGE_TITLE_ICON_NAMES).toHaveLength(29)
    for (const name of PAGE_TITLE_ICON_NAMES) {
      const rendered = renderToStaticMarkup(createElement(PageTitleIcon, { name }))
      expect(rendered, name).toContain('<svg')
      expect(rendered, name).toContain('aria-hidden="true"')
      expect(rendered, name).toContain('stroke="currentColor"')
      expect(rendered, name).not.toMatch(/<img|<image|filter=/)
      expect(fs.existsSync(path.resolve(__dirname, '../../public/page-title-icons', name + '.svg'))).toBe(true)
    }
  })
})
