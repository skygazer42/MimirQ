// @vitest-environment happy-dom

import fs from 'node:fs'
import path from 'node:path'
import chroma from 'chroma-js'
import { describe, expect, it } from 'vitest'

import {
  applyStoredThemeAppearance,
  getSurfaceThemeMeta,
  getThemeColorTokens,
  normalizeSurfaceTheme,
  normalizeThemeColor,
  normalizeThemeColorCookie,
  persistThemeAppearance,
  readThemeColorOverride,
  SURFACE_THEMES,
  SURFACE_THEME_COOKIE_KEY,
  SURFACE_THEME_STORAGE_KEY,
  THEME_COLOR_COOKIE_KEY,
  THEME_COLOR_STORAGE_KEY,
} from './theme-surface'

function createStorage(values: Record<string, string>): Pick<Storage, 'getItem'> {
  return {
    getItem(key) {
      return values[key] ?? null
    },
  }
}

function hslTokenToColor(value: string) {
  return chroma(`hsl(${value})`)
}

describe('theme surface appearance', () => {
  it('keeps default work surfaces neutral and supporting text readable', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../app/globals.css'), 'utf8')
    const rootCss = /:root\s*\{([\s\S]*?)\n\s*\}/u.exec(css)?.[1] ?? ''
    const colorToken = (name: string) => {
      const value = new RegExp(`${name}:\\s*([^;]+);`, 'u').exec(rootCss)?.[1]
      expect(value).toBeTruthy()
      return hslTokenToColor(value ?? '')
    }

    for (const name of ['--background', '--secondary', '--muted', '--sidebar-background', '--surface-2']) {
      const surface = colorToken(name)
      expect(surface.get('lch.c')).toBeLessThan(2.5)
      expect(chroma.contrast(colorToken('--muted-foreground'), surface)).toBeGreaterThanOrEqual(4.5)
    }
    expect(chroma.contrast(colorToken('--foreground'), colorToken('--background'))).toBeGreaterThanOrEqual(4.5)
    expect(css).toContain('--app-background-base: hsl(var(--background))')
    expect(css).toContain('--app-orb-primary-opacity: 0')
    expect(css).toContain('--app-orb-secondary-opacity: 0')
    expect(css).toContain('background-image: none')
  })

  it('keeps the default primary anchored in the approved Ragvia ink', () => {
    const ocean = getSurfaceThemeMeta('ocean')
    expect(ocean.defaultPrimary).toBe('#20262e')

    const tokens = getThemeColorTokens(ocean.defaultPrimary)
    expect(
      chroma.contrast(
        hslTokenToColor(tokens?.['--primary'] || ''),
        hslTokenToColor(tokens?.['--primary-foreground'] || '')
      )
    ).toBeGreaterThanOrEqual(4.5)
  })

  it('recognizes the professional neutral-white surface preset', () => {
    expect(normalizeSurfaceTheme('neutral')).toBe('neutral')
    expect(normalizeSurfaceTheme('deepsea')).toBe('deepsea')
  })

  it('keeps theme previews aligned with valid surface and primary colors', () => {
    expect(SURFACE_THEMES).toHaveLength(5)
    for (const theme of SURFACE_THEMES) {
      expect(chroma.valid(theme.previewSurface)).toBe(true)
      expect(chroma.valid(theme.defaultPrimary)).toBe(true)
    }
    expect(getSurfaceThemeMeta('ocean').previewSurface).toBe('#f6f7f8')
    expect(getSurfaceThemeMeta('deepsea').previewSurface).toBe('#f7f9ff')
  })

  it('keeps surface defaults free from stale inline accent overrides', () => {
    const root = document.createElement('html')
    root.style.setProperty('--primary', '199 89% 48%')
    root.style.setProperty('--info', '199 89% 48%')
    root.style.setProperty('--accent', '225 80% 50%')

    const appearance = applyStoredThemeAppearance(
      createStorage({ [SURFACE_THEME_STORAGE_KEY]: 'neutral' }),
      root,
      null,
      { notify: false }
    )

    expect(appearance).toMatchObject({
      surfaceTheme: 'neutral',
      colorOverride: null,
    })
    expect(root.dataset.surfaceTheme).toBe('neutral')
    expect(root.style.getPropertyValue('--primary')).toBe('')
    expect(root.style.getPropertyValue('--info')).toBe('')
    expect(root.style.getPropertyValue('--accent')).toBe('')
  })

  it('normalizes and applies an explicit readable accent override', () => {
    const storage = createStorage({
      [SURFACE_THEME_STORAGE_KEY]: 'neutral',
      [THEME_COLOR_STORAGE_KEY]: '#18181b',
    })
    const root = document.createElement('html')

    expect(readThemeColorOverride(storage)).toBe('#18181b')
    expect(normalizeThemeColor('not-a-color')).toBeNull()

    const appearance = applyStoredThemeAppearance(storage, root, null, { notify: false })
    const primary = root.style.getPropertyValue('--primary')
    const foreground = root.style.getPropertyValue('--primary-foreground')

    expect(appearance.colorOverride).toBe('#18181b')
    expect(chroma.contrast(hslTokenToColor(primary), hslTokenToColor(foreground))).toBeGreaterThanOrEqual(4.5)

    const skyTokens = getThemeColorTokens('#0ea5e9')
    expect(
      chroma.contrast(
        hslTokenToColor(skyTokens?.['--primary'] || ''),
        hslTokenToColor(skyTokens?.['--primary-foreground'] || '')
      )
    ).toBeGreaterThanOrEqual(4.5)
  })

  it('exposes sanitized color tokens for first-paint server rendering', () => {
    expect(getThemeColorTokens('invalid')).toBeNull()

    const tokens = getThemeColorTokens('#e11d48')
    expect(tokens?.['--primary']).toBeTruthy()
    expect(tokens?.['--primary-foreground']).toBeTruthy()
    expect(tokens?.['--primary-50']).toBeTruthy()
    expect(tokens?.['--primary-900']).toBeTruthy()
  })

  it('persists a preset surface without turning its default color into an override', () => {
    const values = new Map<string, string>()
    const cookieWrites: string[] = []
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    }
    const cookieTarget = {
      set cookie(value: string) {
        cookieWrites.push(value)
      },
    }

    persistThemeAppearance('neutral', null, storage, cookieTarget)

    expect(values.get(SURFACE_THEME_STORAGE_KEY)).toBe('neutral')
    expect(values.has(THEME_COLOR_STORAGE_KEY)).toBe(false)
    expect(cookieWrites).toContainEqual(expect.stringContaining(`${SURFACE_THEME_COOKIE_KEY}=neutral`))
    expect(cookieWrites).toContainEqual(expect.stringContaining(`${THEME_COLOR_COOKIE_KEY}=;`))
  })

  it('round-trips an explicit accent through a cookie-safe value', () => {
    const cookieWrites: string[] = []
    const storage = {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    }
    const cookieTarget = {
      set cookie(value: string) {
        cookieWrites.push(value)
      },
    }

    persistThemeAppearance('classic', '#e11d48', storage, cookieTarget)

    expect(cookieWrites).toContainEqual(expect.stringContaining(`${THEME_COLOR_COOKIE_KEY}=e11d48`))
    expect(normalizeThemeColorCookie('e11d48')).toBe('#e11d48')
    expect(normalizeThemeColorCookie('not-hex')).toBeNull()
  })
})
