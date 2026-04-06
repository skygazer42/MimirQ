import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('select motion source', () => {
  it('uses eased open-close motion for content and rotates the chevron smoothly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'select.tsx'), 'utf8')
    const css = fs.readFileSync(path.resolve(__dirname, '../../app/globals.css'), 'utf8')

    expect(src).toContain('group-data-[state=open]:rotate-180')
    expect(src).toContain('transition-transform duration-200 ease-spring')
    expect(src).toContain('transition-[border-color,background-color,box-shadow,transform] duration-180 ease-out')
    expect(src).toContain('hover:border-border/75 hover:bg-background/96')
    expect(src).toContain('focus-visible:border-primary/45 focus-visible:ring-1 focus-visible:ring-primary/15')
    expect(src).toContain('data-[state=open]:border-primary/40 data-[state=open]:bg-background')
    expect(src).toContain('data-[state=open]:shadow-[0_1px_0_hsl(var(--primary)/0.06)]')
    expect(src).toContain('origin-[var(--radix-select-content-transform-origin)]')
    expect(src).toContain('data-[state=open]:animate-select-content-in')
    expect(src).toContain('data-[state=closed]:animate-select-content-out')
    expect(src).toContain('data-[side=bottom]:[--select-enter-y:-3px]')
    expect(src).toContain('data-[side=top]:[--select-enter-y:3px]')
    expect(src).not.toContain('data-[side=bottom]:translate-y-0.5')
    expect(css).toContain('clip-path: inset(0 0 100% 0 round 0.75rem)')
    expect(css).toContain('scaleY(0.98)')
    expect(css).toContain('clip-path: inset(0 0 0 0 round 0.75rem)')
    expect(src).not.toContain('zoom-in-95')
    expect(src).not.toContain('zoom-out-95')
    expect(css).toContain('@keyframes select-content-in')
    expect(css).toContain('@keyframes select-content-out')
    expect(css).toContain('.animate-select-content-in')
    expect(css).toContain('.animate-select-content-out')
  })
})
