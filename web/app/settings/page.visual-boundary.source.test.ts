// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('settings page visual boundary contract', () => {
  it('uses ruled section frames instead of gradient floating cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src,
      "const SETTINGS_CARD_CLASS = 'rounded-xl border border-info/20 bg-info/[0.025] shadow-none'"
    )
    expectSourceToContain(src,
      'data-testid="settings-metric-strip" className="flex flex-wrap items-center gap-1.5 rounded-xl border border-info/20 bg-info/[0.025] p-1.5"'
    )
    expectSourceToContain(src,
      "'relative scroll-mt-24 overflow-visible rounded-xl border border-info/20 bg-info/[0.018] shadow-none'"
    )
    expectSourceToContain(src,
      '<div className="border-b border-border/60 bg-info/[0.025] px-4 py-3">'
    )
    expectSourceToContain(src, 'bodyClassName="bg-info/[0.035] !pb-3 pt-0.5"')
    expectSourceToContain(src, "indigo: 'text-info'")
    expectSourceToContain(src,
      "? 'border-info/30 bg-info/10'"
    )
    expectSourceNotToContain(src, 'bg-[linear-gradient(90deg')
    expectSourceNotToContain(src, 'before:absolute before:-left-3')
    expectSourceNotToContain(src, 'shadow-[0_14px_34px_hsl(var(--foreground)/0.035)]')
  })

  it('keeps nested settings cards in the Ocean surface family', () => {
    const files = [
      '_sections/feature-flags-section.tsx',
      '_sections/frontend-preferences-section.tsx',
      '_sections/navigation-visibility-section.tsx',
      '_sections/parser-services-section.tsx',
      '_sections/object-storage-section.tsx',
      '_sections/rag-section.tsx',
      '_sections/runtime-controls-section.tsx',
      '_sections/dify-integration-section.tsx',
      '_sections/industry-rules-section.tsx',
    ]
    const combined = files
      .map((file) => fs.readFileSync(path.resolve(__dirname, file), 'utf8'))
      .join('\n')

    expectSourceNotToContain(combined, 'bg-card/82')
    expectSourceNotToContain(combined, 'bg-[linear-gradient(135deg')
  })

  it('keeps navigation visibility groups off white background surfaces', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '_sections/navigation-visibility-section.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'border-info/15 bg-info/[0.025] p-3.5')
    expectSourceToContain(src, 'border-info/15 bg-info/[0.035] p-3')
    expectSourceToContain(src, 'border-info/15 bg-info/[0.025] hover:border-info/25 hover:bg-info/[0.055]')
    expectSourceNotToContain(src, 'bg-background/55')
  })

  it('waits for a wide desktop before showing the settings index', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src,
      'grid gap-4 xl:grid-cols-[176px_minmax(0,1fr)]'
    )
    expectSourceToContain(src, 'xl:block')
    expectSourceNotToContain(src, 'lg:grid-cols-[176px_minmax(0,1fr)]')
  })

  it('keeps provider cards readable at notebook widths', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '_sections/model-providers-section.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'md:grid-cols-2 xl:grid-cols-3')
    expectSourceNotToContain(src, 'md:grid-cols-2 lg:grid-cols-3')
  })

  it('keeps model provider cards off pure card-white surfaces', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../components/model-provider-card.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'border-info/15 bg-info/[0.025]')
    expectSourceToContain(src, 'hover:bg-info/[0.055]')
    expectSourceToContain(src, 'border-info/15 bg-info/[0.05]')
    expectSourceNotToContain(src, 'border bg-card p-3.5')
  })

  it('keeps system status cards off pure card-white surfaces', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '_sections/system-status-section.tsx'),
      'utf8'
    )

    expectSourceToContain(src,
      "'rounded-lg border bg-info/[0.025] px-3 py-2.5 transition-colors'"
    )
    expectSourceToContain(src,
      'rounded-lg border border-info/15 bg-info/[0.025] p-3.5 shadow-none'
    )
    expectSourceNotToContain(src, 'border bg-card px-3 py-2.5')
    expectSourceNotToContain(src, 'border-border/70 bg-card p-3.5')
  })
})
