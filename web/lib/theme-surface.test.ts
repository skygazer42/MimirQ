// @vitest-environment happy-dom

import chroma from 'chroma-js'
import { describe, expect, it } from 'vitest'

import {
  applyStoredThemeAppearance,
  getThemeColorTokens,
  normalizeSurfaceTheme,
  normalizeThemeColor,
  normalizeThemeColorCookie,
  persistThemeAppearance,
  readThemeColorOverride,
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
  it('recognizes the professional neutral-white surface preset', () => {
    expect(normalizeSurfaceTheme('neutral')).toBe('neutral')
    expect(normalizeSurfaceTheme('deepsea')).toBe('deepsea')
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
