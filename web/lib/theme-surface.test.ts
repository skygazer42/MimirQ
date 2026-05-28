// @vitest-environment jsdom

import { describe, expect, it } from 'vitest'

import {
  applyStoredThemeAppearance,
  applySurfaceTheme,
  applyThemeColor,
  getSurfaceThemeMeta,
  normalizeSurfaceTheme,
  readSurfaceTheme,
  readThemeColor,
  THEME_APPEARANCE_CHANGED_EVENT,
  THEME_COLOR_STORAGE_KEY,
} from './theme-surface'

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

  it('reads a valid stored theme color and falls back to the surface preset color', () => {
    expect(readThemeColor({ getItem: () => '#e11d48' }, 'classic')).toBe('#e11d48')
    expect(readThemeColor({ getItem: () => 'not-a-color' }, 'earth')).toBe('#8C6A43')
  })

  it('applies selected color to the primary ramp and info accent tokens', () => {
    const root = document.createElement('html')

    applyThemeColor('#e11d48', root)

    expect(root.style.getPropertyValue('--primary')).toBe('346.8 77.2% 49.8%')
    expect(root.style.getPropertyValue('--primary-500')).toBe('346.8 77.2% 49.8%')
    expect(root.style.getPropertyValue('--info')).toBe('346.8 77.2% 49.8%')
    expect(root.style.getPropertyValue('--ring')).toBe('346.8 77.2% 49.8%')
  })

  it('applies stored theme appearance globally and notifies same-tab listeners', () => {
    const root = document.createElement('html')
    const storage = new Map<string, string>([
      ['mimirq.surfaceTheme', 'earth'],
      [THEME_COLOR_STORAGE_KEY, '#16a34a'],
    ])
    let eventCount = 0
    window.addEventListener(THEME_APPEARANCE_CHANGED_EVENT, () => {
      eventCount += 1
    })

    applyStoredThemeAppearance(
      {
        getItem: (key: string) => storage.get(key) ?? null,
      },
      root,
      window
    )

    expect(root.dataset.surfaceTheme).toBe('earth')
    expect(root.style.getPropertyValue('--primary')).toBe('142.1 76.2% 36.3%')
    expect(eventCount).toBe(1)
  })

  it('exposes default primary colors for presets', () => {
    expect(getSurfaceThemeMeta('classic').defaultPrimary).toBe('#007BFF')
    expect(getSurfaceThemeMeta('earth').defaultPrimary).toBe('#8C6A43')
  })
})
