import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const workbench = fs.readFileSync(
  path.resolve(__dirname, 'components/workbench/index.tsx'),
  'utf8'
)

describe('chunk preview empty workbench cleanup', () => {
  it('preserves upload, drag, example and help behavior', () => {
    expect(workbench).toContain('id="chunk-empty-file-input"')
    expect(workbench).toContain('if (files.length > 0) addFiles(files)')
    expect(workbench).toContain('onDragOver={handleDragOver}')
    expect(workbench).toContain('onDragLeave={handleDragLeave}')
    expect(workbench).toContain('onDrop={handleDrop}')
    expect(workbench).toContain('onClick={() => setHelpOpen(true)}')
    expect(workbench).toContain('onClick={item.action}')
  })

  it('uses flat sections, restrained typography and linear icons', () => {
    expect(workbench).toContain('data-chunk-empty-intake-panel')
    expect(workbench).toContain(
      'className="border-b border-foreground/10 pb-5"'
    )
    expect(workbench).toContain(
      'className="max-w-2xl text-xl font-medium tracking-[-0.02em] text-foreground md:text-[22px]"'
    )
    expect(workbench).toContain(
      'className="divide-y divide-foreground/10 border-y border-foreground/10"'
    )
    expect(workbench).toContain(
      'className="relative border-t border-foreground/10 pt-5 xl:border-l xl:border-t-0 xl:pl-5 xl:pt-0"'
    )
    expect(workbench).toContain(
      'className="relative flex items-center gap-3 border-b border-foreground/10 py-3 last:border-b-0"'
    )
    expect(workbench).not.toContain('font-black')
    expect(workbench).not.toContain('group/card relative h-full space-y-3 rounded-2xl border')
    expect(workbench).not.toContain("accent: 'text-warning'")
    expect(workbench).not.toContain("tone: 'text-success'")
    expect(workbench).toContain('paneGroupClassName="gap-5 xl:gap-6"')
  })

  it('waits for xl before splitting narrow workbench containers', () => {
    expect(workbench).toContain('xl:flex-row xl:items-stretch xl:justify-between')
    expect(workbench).toContain('xl:w-[24rem]')
    expect(workbench).toContain(
      'xl:grid-cols-[minmax(0,0.82fr)_minmax(24rem,1fr)]'
    )
    expect(workbench).toContain(
      'xl:grid-cols-[0.9fr_1.1fr] xl:items-stretch'
    )
    expect(workbench).toContain('xl:border-r xl:border-foreground/10 xl:pr-4')
    expect(workbench).not.toContain('lg:flex-row lg:items-stretch lg:justify-between')
  })
})
