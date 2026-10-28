// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain } from '@/lib/source-test-utils'

const SETTINGS_THEME_FILES = [
  'page.tsx',
  '_sections/feature-flags-section.tsx',
  '_sections/frontend-preferences-section.tsx',
  '_sections/governance-section.tsx',
  '_sections/industry-rules-section.tsx',
  '_sections/model-providers-section.tsx',
  '_sections/navigation-visibility-section.tsx',
  '_sections/observability-section.tsx',
  '_sections/parser-services-section.tsx',
  '_sections/rag-section.tsx',
  '_sections/runtime-controls-section.tsx',
  '_sections/dify-integration-section.tsx',
  '../../components/model-provider-card.tsx',
  '../../components/settings/settings-switch.tsx',
  '../../components/settings/danger-zone-panel.tsx',
  '../../components/settings/governance-ops-panel.tsx',
  '../../components/ui/system-page-tokens.ts',
] as const

function readSettingsThemeSources(): string {
  return SETTINGS_THEME_FILES
    .map((file) => fs.readFileSync(path.resolve(__dirname, file), 'utf8'))
    .join('\n')
}

describe('settings theme boundaries', () => {

  it('does not invert persistent settings surfaces across themes', () => {
    const src = readSettingsThemeSources()

    expectSourceNotToContain(src, 'bg-foreground')
    expectSourceNotToContain(src, 'text-background')
    expectSourceNotToContain(src, 'bg-background/55')
    expectSourceNotToContain(src, 'bg-background/60')
  })


  it('uses one active feature style instead of decorative warning and success colors', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '_sections/feature-flags-section.tsx'),
      'utf8'
    )

    expectSourceNotToContain(src, "color: 'orange'")
    expectSourceNotToContain(src, "color: 'green'")
    expectSourceNotToContain(src, 'bg-warning/10')
    expectSourceNotToContain(src, 'bg-success/10')
  })



})
