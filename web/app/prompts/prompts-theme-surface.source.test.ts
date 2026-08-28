import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const pageSource = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

describe('prompts Ocean theme', () => {
  it('uses one coherent surface and control system', () => {
    expect(pageSource).toContain(
      "const PROMPT_SURFACE_CLASS =\n  'rounded-xl border border-info/15 bg-background/72 shadow-none'"
    )
    expect(pageSource).toContain(
      "const PROMPT_CONTROL_CLASS =\n  'rounded-lg border-info/15 bg-info/[0.025] shadow-none'"
    )
    expect(pageSource).toContain('bodyClassName="bg-info/[0.035] !pb-0"')
    expect(pageSource).toContain('border-b border-info/15 bg-info/[0.025]')
    expect(pageSource).toContain('hover:bg-info/[0.025]')
  })

  it('removes decorative gradients and card shadows from the workbench', () => {
    expect(pageSource).not.toContain('!bg-[linear-gradient')
    expect(pageSource).not.toContain('bg-[linear-gradient(180deg')
    expect(pageSource).not.toContain('shadow-[0_1px_0_rgba(15,23,42,0.03)]')
    expect(pageSource).not.toContain('shadow-[0_18px_50px_rgba(15,23,42,0.14)]')
  })
})
