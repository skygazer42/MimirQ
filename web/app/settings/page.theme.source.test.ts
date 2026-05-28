import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const ROUTE_THEME_FILES = [
  './page.tsx',
  './_sections/dify-integration-section.tsx',
  './_sections/feature-flags-section.tsx',
  './_sections/frontend-preferences-section.tsx',
  './_sections/governance-section.tsx',
  './_sections/industry-rules-section.tsx',
  './_sections/ltr-model-registry-section.tsx',
  './_sections/model-providers-section.tsx',
  './_sections/navigation-visibility-section.tsx',
  './_sections/observability-section.tsx',
  './_sections/parser-services-section.tsx',
  './_sections/rag-section.tsx',
  './_sections/runtime-controls-section.tsx',
  './_sections/system-status-section.tsx',
  './_sections/url-ingest-section.tsx',
  '../../components/business/chunk-strategy-dropdown.tsx',
  '../../components/business/parser-dropdown.tsx',
  '../../components/model-provider-card.tsx',
  '../../components/pipeline-options-panel.tsx',
  '../../components/settings/danger-zone-panel.tsx',
  '../../components/settings/governance-ops-panel.tsx',
  '../../components/settings/settings-switch.tsx',
  '../../components/ui/page-header.tsx',
  '../../components/ui/system-page-tokens.ts',
] as const

const FIXED_PALETTE_CLASS =
  /\b(?:bg|text|border|ring|from|via|to|hover:bg|hover:text|hover:border|disabled:bg|placeholder:text|accent|focus-visible:ring)-(?:slate|blue|indigo|purple|red|emerald|amber|rose|cyan|teal|sky|orange|fuchsia)-[\w/.[\]-]+|\b(?:bg|text|border|ring|from|via|to)-white(?:\/[\w.[\]-]+)?|rgba\(/g

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('settings page theme tokens', () => {
  it('keeps the main settings route free of fixed blue-white-slate palette classes', () => {
    const violations = ROUTE_THEME_FILES.flatMap((file) => {
      const src = read(file)
      return Array.from(src.matchAll(FIXED_PALETTE_CLASS)).map((match) => `${file}: ${match[0]}`)
    })

    expect(violations).toEqual([])
  })
})
