import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (file: string) =>
  fs.readFileSync(path.resolve(__dirname, file), 'utf8')

describe('chunk preview theme and compact icon', () => {
  it('uses the shared Ocean canvas without decorative glow layers', () => {
    const workbench = read('components/workbench/index.tsx')

    expect(workbench).toContain(
      "'relative flex h-full min-h-0 flex-1 items-start overflow-y-auto overscroll-contain bg-info/[0.035] transition-colors duration-500'"
    )
    expect(workbench).not.toContain('circle_at_18%_12%')
    expect(workbench).not.toContain("bg-[url('/grid.svg')]")
    expect(workbench).not.toContain('-right-16 -top-20 size-56')
    expect(workbench).not.toContain('-bottom-20 left-1/4 size-48')
  })

  it('keeps the workbench structure and routes the page title to a compact SVG', () => {
    const workbench = read('components/workbench/index.tsx')
    const pageTitleIcon = read('../ui/page-title-icon.tsx')
    const icon = read('../../public/page-title-icons/chunk-preview.svg')

    expect(workbench).toContain('iconImage="chunk-preview"')
    expect(workbench).toContain('data-chunk-preview-empty-canvas="true"')
    expect(workbench).toContain('data-chunk-empty-visual-map')
    expect(pageTitleIcon).toContain(
      '"chunk-preview": "/page-title-icons/chunk-preview.svg"'
    )
    expect(pageTitleIcon).toContain(
      'src={PAGE_TITLE_ICON_SOURCES[name] ?? `/page-title-icons/${name}.png`}'
    )
    expect(icon).toContain('<svg')
    expect(icon).toContain('data-chunk-boundary="true"')
    expect(icon).toContain('data-chunk-overlap="true"')
  })
})
