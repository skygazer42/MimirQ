import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('quality checker source', () => {
  it('uses codePoint helpers and extracted issue collectors instead of inline parsing hotspots', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'quality-checker.tsx'), 'utf8')

    expect(src).toContain('function getLeadingCodePoint(')
    expect(src).toContain('function collectLocalQualityIssues(')
    expect(src).toContain('function getBackendQualityIssues(')
    expect(src).toContain('codePointAt(0)')
    expect(src).not.toContain('charCodeAt(0)')
    expect(src).not.toContain('format: (() => {')
  })

  it('keeps backend scan and rescan controls on light semantic surfaces', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'quality-checker.tsx'), 'utf8')

    expect(src).not.toContain("variant={backendScanEnabled ? 'default' : 'outline'}")
    expect(src).toContain('const backendScanToggleClass = cn(')
    expect(src).toContain('border-success/25 bg-success/10 text-success')
    expect(src).toContain('border-info/25 bg-info/10 text-info')
    expect(src).toContain('border-info/25 border-t-info')
  })

  it('keeps the quality score header and score card compact', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'quality-checker.tsx'), 'utf8')

    expect(src).not.toContain('text-4xl font-medium text-foreground')
    expect(src).not.toContain('flex h-16 w-16 items-center justify-center rounded-full border-4')
    expect(src).not.toContain('text-2xl font-medium')
    expect(src).toContain('const scoreCardClass =')
    expect(src).toContain('text-[28px] font-semibold leading-none text-foreground')
    expect(src).toContain('flex h-12 w-12 items-center justify-center rounded-full border-2')
    expect(src).toContain('text-[18px] font-semibold leading-none')
  })
})
