// @vitest-environment happy-dom

import fs from 'node:fs'
import path from 'node:path'
import chroma from 'chroma-js'
import { describe, expect, it } from 'vitest'

import {
  applyStoredThemeAppearance,
  getSurfaceThemeMeta,
  normalizeSurfaceTheme,
  normalizeThemeColor,
  normalizeThemeColorCookie,
  persistThemeAppearance,
  readThemeColorOverride,
  SURFACE_THEMES,
  SURFACE_THEME_COOKIE_KEY,
  SURFACE_THEME_STORAGE_KEY,
  THEME_ACCENT_COLORS,
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

const css = fs.readFileSync(path.resolve(__dirname, '../app/globals.css'), 'utf8')
const rootCss = /:root\s*\{([\s\S]*?)\n\s*\}/u.exec(css)?.[1] ?? ''

function tokenColor(rule: string, name: string) {
  const value = new RegExp(`${name}:\\s*([^;]+);`, 'u').exec(rule)?.[1]
  if (value === undefined) throw new Error(`Missing CSS token: ${name}`)
  return chroma(`hsl(${value})`)
}

describe('theme surface appearance', () => {
  it('keeps default work surfaces neutral and supporting text readable', () => {
    for (const name of ['--background', '--secondary', '--muted', '--sidebar-background', '--surface-2']) {
      const surface = tokenColor(rootCss, name)
      expect(surface.get('lch.c')).toBeLessThan(2.5)
      expect(chroma.contrast(tokenColor(rootCss, '--muted-foreground'), surface)).toBeGreaterThanOrEqual(4.5)
    }
    expect(
      chroma.contrast(tokenColor(rootCss, '--foreground'), tokenColor(rootCss, '--background')),
    ).toBeGreaterThanOrEqual(4.5)
    expect(css).toContain('--app-background-base: hsl(var(--background))')
    expect(css).toContain('--app-orb-primary-opacity: 0')
    expect(css).toContain('--app-orb-secondary-opacity: 0')
    expect(css).toContain('background-image: none')
  })

  it('keeps the default primary anchored in the approved Ragvia ink', () => {
    const ocean = getSurfaceThemeMeta('ocean')
    expect(ocean.defaultPrimary).toBe('#20262e')

    expect(
      chroma.contrast(tokenColor(rootCss, '--primary'), tokenColor(rootCss, '--primary-foreground')),
    ).toBeGreaterThanOrEqual(4.5)
  })

  it('recognizes current surface presets and normalizes an old preset', () => {
    expect(normalizeSurfaceTheme('neutral')).toBe('neutral')
    expect(normalizeSurfaceTheme('deepsea')).toBe('ocean')
  })

  it('keeps theme previews aligned with valid surface and primary colors', () => {
    expect(SURFACE_THEMES).toHaveLength(4)
    for (const theme of SURFACE_THEMES) {
      expect(chroma.valid(theme.previewSurface)).toBe(true)
      expect(chroma.valid(theme.defaultPrimary)).toBe(true)
    }
    expect(getSurfaceThemeMeta('ocean').previewSurface).toBe('#ffffff')
    expect(getSurfaceThemeMeta('classic').previewSurface).toBe('#f6f7f8')
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
      { notify: false },
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
    expect(appearance.colorOverride).toBe('#18181b')
    expect(root.dataset.themeColor).toBe('18181b')
    const graphite = /html\[data-theme-color='18181b'\]\s*\{([^}]+)\}/u.exec(css)?.[1] ?? ''
    expect(
      chroma.contrast(tokenColor(graphite, '--primary'), tokenColor(graphite, '--primary-foreground')),
    ).toBeGreaterThanOrEqual(4.5)
  })

  it('defines stylesheet rules for each allowed accent', () => {
    expect(normalizeThemeColor('#e11d48')).toBeNull()
    for (const { value } of THEME_ACCENT_COLORS) {
      expect(css).toContain(`html[data-theme-color='${value.slice(1)}']`)
    }
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

    persistThemeAppearance('classic', '#c85a32', storage, cookieTarget)

    expect(cookieWrites).toContainEqual(expect.stringContaining(`${THEME_COLOR_COOKIE_KEY}=c85a32`))
    expect(normalizeThemeColorCookie('c85a32')).toBe('#c85a32')
    expect(normalizeThemeColorCookie('not-hex')).toBeNull()
  })
})
