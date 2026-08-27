// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readSource(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('evaluation support surfaces stay flat', () => {
  it('avoids glass panels and glow overlays in queryset health and radar widgets', () => {
    const querysetHealthSrc = readSource('./queryset-health-tab-client.tsx')
    const radarSrc = readSource('./holographic-radar-client.tsx')

    expect(querysetHealthSrc).not.toContain('variant="glass"')
    expect(querysetHealthSrc).not.toContain('backdrop-blur')

    expect(radarSrc).not.toContain('backdrop-blur')
    expect(radarSrc).not.toContain('blur-2xl')
    expect(radarSrc).not.toContain('shadow-strong')
  })

  it('removes decorative empty-state bubbles and gradients from ablation workflows', () => {
    const ablationsSrc = readSource('./retrieval-ablations-page.tsx')

    expect(ablationsSrc).not.toContain('ablation-empty-illustration')
    expect(ablationsSrc).not.toContain('shadow-[0_16px_42px_hsl(var(--primary)/0.12)]')
    expect(ablationsSrc).not.toContain('shadow-[0_14px_30px_hsl(var(--primary)/0.22)]')
    expect(ablationsSrc).not.toContain('shadow-[0_18px_44px_hsl(var(--warning)/0.32)]')
    expect(ablationsSrc).not.toContain('bg-[linear-gradient(180deg,hsl(var(--background))_0%,hsl(var(--muted)/0.35)_40%,hsl(var(--background))_100%)]')
  })
})
