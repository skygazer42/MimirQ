import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readComponent(): string {
  return fs.readFileSync(
    path.resolve(__dirname, 'chunk-strategy-dropdown.tsx'),
    'utf8'
  )
}

describe('ChunkStrategyDropdown source contract', () => {
  it('renders the option menu in a body-level portal to avoid parent clipping', () => {
    const source = readComponent()

    expect(source).toContain("import { createPortal } from 'react-dom'")
    expect(source).toContain('createPortal(')
    expect(source).toContain('document.body')
    expect(source).toContain("className=\"fixed z-[1000]")
    expect(source).toContain('window.addEventListener(\'scroll\', updateMenuPlacement, true)')
    expect(source).not.toContain('placeholder="搜索切块方式..."')
    expect(source).not.toContain('setQuery')
  })

  it('keeps the selected trigger typography aligned with parser dropdown', () => {
    const source = readComponent()

    expect(source).toContain('truncate text-[13px] font-medium text-foreground')
    expect(source).toContain('mt-0.5 truncate text-[11px] leading-4 text-muted-foreground')
    expect(source).toContain('py-px text-[9px] font-medium leading-4')
  })

  it('keeps strategy option rows visually stable across different copy lengths', () => {
    const source = readComponent()

    expect(source).toContain('h-[72px] w-full')
    expect(source).toContain('size-8 shrink-0')
    expect(source).toContain('line-clamp-2 text-[11px] leading-4 text-muted-foreground')
    expect(source).toContain('h-[60px] w-full')
    expect(source).toContain('min-w-0 flex-1 text-left')
  })
})
