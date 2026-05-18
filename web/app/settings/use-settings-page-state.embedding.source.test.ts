import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings page state embedding providers', () => {
  it('syncs DashScope embedding config into provider cards and persists embedding updates', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-settings-page-state.ts'), 'utf8')

    expect(src).toContain('function resolveEmbeddingProviderId')
    expect(src).toContain("return 'qwen-embedding'")
    expect(src).toContain("if (provider.category === 'model' || provider.category === 'embedding')")
    expect(src).toContain('embedding: {')
    expect(src).toContain('provider: resolveEmbeddingProvider(provider.id)')
    expect(src).toContain('setProviders(hydrateProvidersFromSettings(MODEL_PROVIDERS, settings))')
  })
})
