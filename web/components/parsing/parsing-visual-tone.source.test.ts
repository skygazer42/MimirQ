import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (file: string) =>
  fs.readFileSync(path.resolve(__dirname, file), 'utf8')

describe('parsing workbench visual tone', () => {
  it('uses one Ocean canvas instead of a decorative page gradient', () => {
    const shell = read('parsing-workbench-shell.tsx')

    expect(shell).toContain('<AppFrame mainClassName="bg-background">')
    expect(shell).not.toContain('pipelineRail=')
    expect(shell).not.toContain('PipelineRail')
    expect(shell).not.toContain('mainClassName="bg-[radial-gradient(')
  })

  it('keeps the main empty canvas theme-neutral with a quieter grid', () => {
    const shell = read('parsing-workbench-shell.tsx')

    expect(shell).toContain("'relative overflow-hidden rounded-[24px] border bg-background shadow-none'")
    expect(shell).toContain('className="flex flex-1 min-h-0 min-w-0 flex-col overflow-hidden bg-background"')
    expect(shell).toContain('className="relative flex flex-1 items-center justify-center overflow-hidden bg-background"')
    expect(shell).toContain('hsl(var(--foreground)/0.035)')
    expect(shell).not.toContain('circle_at_50%_38%')
  })

  it('brings both side rails back to the same themed surface', () => {
    const shell = read('parsing-workbench-shell.tsx')
    const left = read('parsing-left-panel.tsx')

    expect(left).toContain('bg-background/90')
    expect(left).not.toContain('bg-card/96')
    expect(shell).toContain('bg-background/90 p-4')
    expect(shell).toContain('bg-muted/15')
    expect(shell).not.toContain('bg-card/96 p-4')
    expect(shell).not.toContain('bg-card/80')
  })
})
