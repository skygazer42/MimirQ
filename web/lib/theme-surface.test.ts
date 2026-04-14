import { describe, expect, it } from 'vitest'

import { applySurfaceTheme, getSurfaceThemeMeta, normalizeSurfaceTheme, readSurfaceTheme } from './theme-surface'

describe('theme surface helpers', () => {
  it('normalizes unknown values to ocean', () => {
    expect(normalizeSurfaceTheme('weird')).toBe('ocean')
    expect(normalizeSurfaceTheme('classic')).toBe('classic')
    expect(normalizeSurfaceTheme('earth')).toBe('earth')
  })

  it('reads stored theme from storage-like objects', () => {
    expect(readSurfaceTheme({ getItem: () => 'classic' })).toBe('classic')
    expect(readSurfaceTheme({ getItem: () => 'earth' })).toBe('earth')
    expect(readSurfaceTheme({ getItem: () => 'bad' })).toBe('ocean')
  })

  it('applies the theme as a root dataset attribute', () => {
    const root = { dataset: {} } as HTMLElement
    applySurfaceTheme('earth', root)
    expect(root.dataset.surfaceTheme).toBe('earth')
  })

  it('exposes default primary colors for presets', () => {
    expect(getSurfaceThemeMeta('classic').defaultPrimary).toBe('#007BFF')
    expect(getSurfaceThemeMeta('earth').defaultPrimary).toBe('#8C6A43')
  })
})
