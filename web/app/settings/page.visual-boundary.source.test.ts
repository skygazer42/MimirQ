// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('settings page visual boundary contract', () => {
  it('uses ruled section frames instead of gradient floating cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceNotToContain(src, 'bg-[linear-gradient(90deg')
    expectSourceNotToContain(src, 'before:absolute before:-left-3')
    expectSourceNotToContain(src, 'shadow-[0_14px_34px_hsl(var(--foreground)/0.035)]')
  })

  it('avoids legacy layered gradients inside settings sections', () => {
    const files = [
      '_sections/feature-flags-section.tsx',
      '_sections/frontend-preferences-section.tsx',
      '_sections/navigation-visibility-section.tsx',
      '_sections/parser-services-section.tsx',
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


  it('waits for a wide desktop before showing the settings index', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src, 'xl:block')
    expectSourceNotToContain(src, 'lg:grid-cols-[176px_minmax(0,1fr)]')
  })



})
