import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (file: string) =>
  fs.readFileSync(path.resolve(__dirname, file), 'utf8')

describe('parsing sidebar density', () => {
  it('uses a compact document toolbar on the shared workbench surface', () => {
    const sidebar = read('parsing-sidebar-pane.tsx')

    expect(sidebar).toContain(
      'className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-border/55 bg-background px-3 py-2"'
    )
    expect(sidebar).toContain('className="flex size-7 shrink-0 items-center justify-center rounded-lg')
  })

  it('keeps dataset scope in one flat row without a duplicate status badge', () => {
    const sidebar = read('parsing-sidebar-pane.tsx')

    expect(sidebar).toContain(
      'className="flex items-center gap-2 border-b border-border/55 bg-background px-3 py-2"'
    )
    expect(sidebar).toContain('className="h-8 min-w-0 flex-1 rounded-lg')
    expect(sidebar).not.toContain("t('sidebar.datasetScoped')")
    expect(sidebar).not.toContain("t('sidebar.datasetAll')")
    expect(sidebar).not.toContain(
      'bg-[linear-gradient(90deg,hsl(var(--info)/0.07),transparent)]'
    )
  })

  it('uses Chinese copy and one continuous surface for the folder tree', () => {
    const sidebar = read('parsing-sidebar-pane.tsx')
    const messages = read('../../i18n/messages/zh-CN/parsing.ts')

    expect(messages).toContain("datasetScope: '数据范围'")
    expect(sidebar).toContain(
      'className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-background px-2.5 py-2"'
    )
  })
})
