import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('PageHeader source', () => {
  it('uses a consistent title shell with tokenized accent styling', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-header.tsx'), 'utf8')

    expect(src).toContain('data-testid="page-title-shell"')
    expect(src).toContain('rounded-[24px]')
    expect(src).toContain('bg-[linear-gradient(135deg,hsl(var(--card)/0.98),hsl(var(--muted)/0.34))]')
    expect(src).toContain('bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent')
    expect(src).toContain('bg-info/55')
    expect(src).toContain('backdrop-blur-xl')
    expect(src).toContain('text-4xl md:text-5xl')
    expect(src).toContain('tracking-[-0.03em]')
    expect(src).toContain('leading-[1.75]')
  })

  it('allows dense action groups to wrap instead of crushing the title', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-header.tsx'), 'utf8')

    expect(src).toContain('children && "lg:flex-1"')
    expect(src).toContain('flex-wrap items-center justify-start gap-2 lg:justify-end')
  })
})
