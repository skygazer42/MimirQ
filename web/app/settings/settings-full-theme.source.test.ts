// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

const SETTINGS_THEME_FILES = [
  'page.tsx',
  '_sections/feature-flags-section.tsx',
  '_sections/frontend-preferences-section.tsx',
  '_sections/governance-section.tsx',
  '_sections/industry-rules-section.tsx',
  '_sections/ltr-model-registry-section.tsx',
  '_sections/model-providers-section.tsx',
  '_sections/navigation-visibility-section.tsx',
  '_sections/object-storage-section.tsx',
  '_sections/observability-section.tsx',
  '_sections/parser-services-section.tsx',
  '_sections/rag-section.tsx',
  '_sections/runtime-controls-section.tsx',
  '_sections/url-ingest-section.tsx',
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

describe('settings full-page Ocean theme contract', () => {
  it('uses info as the only non-semantic settings accent', () => {
    const src = readSettingsThemeSources()

    expectSourceNotToContain(src, 'bg-primary')
    expectSourceNotToContain(src, 'text-primary')
    expectSourceNotToContain(src, 'border-primary')
    expectSourceNotToContain(src, 'ring-primary')
    expectSourceNotToContain(src, 'var(--primary)')
    expectSourceNotToContain(src, 'primary-foreground')
  })

  it('does not invert persistent settings surfaces across themes', () => {
    const src = readSettingsThemeSources()

    expectSourceNotToContain(src, 'bg-foreground')
    expectSourceNotToContain(src, 'text-background')
    expectSourceNotToContain(src, 'bg-background/55')
    expectSourceNotToContain(src, 'bg-background/60')
  })

  it('keeps the settings switch on the Ocean accent without decorative shadows', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../components/settings/settings-switch.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'data-[switch-state=checked]:border-info/45')
    expectSourceToContain(src, 'data-[switch-state=checked]:[&>span]:bg-info')
    expectSourceNotToContain(src, 'shadow-[')
    expectSourceNotToContain(src, 'shadow-inner')
  })

  it('uses one active feature style instead of decorative warning and success colors', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '_sections/feature-flags-section.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "const FEATURE_FLAG_ACTIVE_STYLE = {")
    expectSourceNotToContain(src, "color: 'orange'")
    expectSourceNotToContain(src, "color: 'green'")
    expectSourceNotToContain(src, 'bg-warning/10')
    expectSourceNotToContain(src, 'bg-success/10')
  })

  it('keeps the Dify endpoint as an Ocean inset surface in both themes', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '_sections/dify-integration-section.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'border-info/20 bg-info/[0.07]')
    expectSourceToContain(src, 'text-info')
    expectSourceNotToContain(src, 'bg-foreground')
  })

  it('overrides shared panel backgrounds inside every settings section', () => {
    const files = [
      '_sections/model-providers-section.tsx',
      '_sections/governance-section.tsx',
      '_sections/industry-rules-section.tsx',
      '_sections/ltr-model-registry-section.tsx',
    ]
    const combined = files
      .map((file) => fs.readFileSync(path.resolve(__dirname, file), 'utf8'))
      .join('\n')

    expectSourceToContain(combined, "systemWorkbenchTokens.panel, 'border-info/15 bg-info/[0.025]")
    expectSourceNotToContain(combined, "systemWorkbenchTokens.panel, 'p-3.5'")
    expectSourceNotToContain(combined, "systemWorkbenchTokens.panel, 'space-y-3 p-3.5'")
    expectSourceNotToContain(combined, "systemWorkbenchTokens.panel, 'space-y-3.5 p-3.5'")
  })

  it('opts both frontend preference dropdowns into their Ocean surfaces', () => {
    const section = fs.readFileSync(
      path.resolve(__dirname, '_sections/frontend-preferences-section.tsx'),
      'utf8'
    )
    const parser = fs.readFileSync(
      path.resolve(__dirname, '../../components/business/parser-dropdown.tsx'),
      'utf8'
    )
    const chunk = fs.readFileSync(
      path.resolve(__dirname, '../../components/business/chunk-strategy-dropdown.tsx'),
      'utf8'
    )

    expectSourceToContain(parser, "surface?: 'default' | 'ocean'")
    expectSourceToContain(parser, "surface === 'ocean'")
    const oceanMenuSurface =
      'border-info/30 bg-[linear-gradient(hsl(var(--info)/0.10),hsl(var(--info)/0.10)),linear-gradient(hsl(var(--popover)),hsl(var(--popover)))] text-popover-foreground shadow-strong'
    expectSourceToContain(parser, oceanMenuSurface)
    expectSourceToContain(chunk, oceanMenuSurface)
    expectSourceToContain(section,
      '<ParserDropdown value={parserBackend} onChange={setParserBackend} surface="ocean"'
    )
    expectSourceToContain(section,
      '<ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} surface="ocean"'
    )
  })
})
