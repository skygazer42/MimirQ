import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('theme appearance provider source', () => {
  it('mounts a global appearance provider from the root layout', () => {
    const layout = read('../app/layout.tsx')

    expect(layout).toContain("import { ThemeAppearanceProvider } from '@/components/theme-appearance-provider'")
    expect(layout).toContain('<ThemeAppearanceProvider />')
  })

  it('re-applies stored personalization outside the customizer popover', () => {
    const src = read('./theme-appearance-provider.tsx')

    expect(src).toContain('applyStoredThemeAppearance')
    expect(src).toContain('THEME_APPEARANCE_CHANGED_EVENT')
    expect(src).toContain("window.addEventListener('storage'")
    expect(src).toContain('SURFACE_THEME_STORAGE_KEY')
    expect(src).toContain('THEME_COLOR_STORAGE_KEY')
  })

  it('uses a themed application background instead of a flat bg-background layer', () => {
    const src = read('./ui/app-background.tsx')

    expect(src).toContain('app-background__base')
    expect(src).toContain('app-background__orb-primary')
    expect(src).toContain('app-background__orb-secondary')
    expect(src).not.toContain('absolute inset-0 bg-background')
  })
})
