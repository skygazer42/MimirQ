import chroma, { type Color } from 'chroma-js'
import { getClientStorage } from './client-storage'

export type SurfaceThemeKey = 'ocean' | 'neutral' | 'classic' | 'earth'

export const SURFACE_THEME_STORAGE_KEY = 'mimirq.surfaceTheme'
export const THEME_COLOR_STORAGE_KEY = 'mimirq.themeColor'
export const SURFACE_THEME_COOKIE_KEY = 'mimirq_surface_theme'
export const THEME_COLOR_COOKIE_KEY = 'mimirq_theme_color'
export const THEME_APPEARANCE_CHANGED_EVENT = 'mimirq:theme-appearance-changed'

const THEME_COLOR_TOKEN_NAMES = [
  '--primary',
  '--ring',
  '--primary-foreground',
  '--info',
  '--info-foreground',
  '--accent',
  '--accent-foreground',
  '--primary-50',
  '--primary-100',
  '--primary-200',
  '--primary-300',
  '--primary-400',
  '--primary-500',
  '--primary-600',
  '--primary-700',
  '--primary-800',
  '--primary-900',
] as const

type StorageReader = Pick<Storage, 'getItem'>
type StorageWriter = Pick<Storage, 'setItem' | 'removeItem'>
type ThemeEventTarget = Pick<Window, 'dispatchEvent'>
type ThemeCookieTarget = { cookie: string }

type ApplyThemeAppearanceOptions = {
  notify?: boolean
}

export const SURFACE_THEMES: Array<{
  key: SurfaceThemeKey
  label: string
  description: string
  defaultPrimary: string
}> = [
  {
    key: 'ocean',
    label: 'Ocean',
    description: '冷静蓝绿，保持当前默认观感。',
    defaultPrimary: '#0f172a',
  },
  {
    key: 'neutral',
    label: 'Neutral',
    description: '瓷白表面与石墨层级，仅让必要的业务状态着色。',
    defaultPrimary: '#18181b',
  },
  {
    key: 'classic',
    label: 'Classic',
    description: '经典白灰，浅灰白背景配深灰正文与蓝色强调。',
    defaultPrimary: '#0062cc',
  },
  {
    key: 'earth',
    label: 'Earth',
    description: '暖米白背景，阅读更柔和，适合长时间停留。',
    defaultPrimary: '#8C6A43',
  },
]

export function normalizeSurfaceTheme(value?: string | null): SurfaceThemeKey {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'neutral' || raw === 'classic' || raw === 'earth') return raw
  return 'ocean'
}

export function getSurfaceThemeMeta(theme: SurfaceThemeKey) {
  return SURFACE_THEMES.find((item) => item.key === theme) || SURFACE_THEMES[0]
}

export function readSurfaceTheme(storage?: StorageReader | null): SurfaceThemeKey {
  return normalizeSurfaceTheme(storage?.getItem(SURFACE_THEME_STORAGE_KEY))
}

export function applySurfaceTheme(theme: SurfaceThemeKey, root?: HTMLElement | null) {
  const target = root ?? (typeof document === 'undefined' ? null : document.documentElement)
  if (!target) return
  target.dataset.surfaceTheme = normalizeSurfaceTheme(theme)
}

function toHsl(color: Color): string {
  const [hue, saturation, lightness] = color.hsl()
  const safeHue = Number.isFinite(hue) ? hue : 0

  return `${safeHue.toFixed(1)} ${(saturation * 100).toFixed(1)}% ${(lightness * 100).toFixed(1)}%`
}

function getReadableForeground(color: Color): Color {
  return chroma.contrast(color, 'white') >= 4.5 ? chroma('white') : chroma('black')
}

export function readThemeColor(
  storage?: StorageReader | null,
  surfaceTheme: SurfaceThemeKey = 'ocean'
): string {
  const storedColor = storage?.getItem(THEME_COLOR_STORAGE_KEY)
  if (storedColor && chroma.valid(storedColor)) {
    return chroma(storedColor).hex()
  }
  return getSurfaceThemeMeta(surfaceTheme).defaultPrimary
}

export function normalizeThemeColor(value?: string | null): string | null {
  const candidate = String(value || '').trim()
  if (!candidate || !chroma.valid(candidate)) return null
  return chroma(candidate).hex()
}

export function normalizeThemeColorCookie(value?: string | null): string | null {
  const candidate = String(value || '').trim()
  if (!/^[0-9a-f]{6}$/iu.test(candidate)) return null
  return normalizeThemeColor(`#${candidate}`)
}

export function readThemeColorOverride(storage?: StorageReader | null): string | null {
  return normalizeThemeColor(storage?.getItem(THEME_COLOR_STORAGE_KEY))
}

export function getThemeColorTokens(color: string): Record<string, string> | null {
  const normalized = normalizeThemeColor(color)
  if (!normalized) return null

  const primary = chroma(normalized)
  const foreground = getReadableForeground(primary)
  const primaryHue = primary.get('hsl.h')
  const primarySaturation = primary.get('hsl.s')
  const accent =
    Number.isFinite(primarySaturation) && primarySaturation < 0.12
      ? primary.mix('white', 0.16, 'rgb')
      : primary
          .set('hsl.h', Number.isFinite(primaryHue) ? (primaryHue + 26) % 360 : 211)
          .saturate(0.35)
  const ramp: Array<[string, Color]> = [
    ['--primary-50', primary.mix('white', 0.92, 'rgb')],
    ['--primary-100', primary.mix('white', 0.82, 'rgb')],
    ['--primary-200', primary.mix('white', 0.68, 'rgb')],
    ['--primary-300', primary.mix('white', 0.48, 'rgb')],
    ['--primary-400', primary.mix('white', 0.24, 'rgb')],
    ['--primary-500', primary],
    ['--primary-600', primary.darken(0.35)],
    ['--primary-700', primary.darken(0.75)],
    ['--primary-800', primary.darken(1.15)],
    ['--primary-900', primary.darken(1.55)],
  ]
  const tokens: Record<string, string> = {
    '--primary': toHsl(primary),
    '--ring': toHsl(primary),
    '--primary-foreground': toHsl(foreground),
    '--info': toHsl(primary),
    '--info-foreground': toHsl(foreground),
    '--accent': toHsl(accent),
    '--accent-foreground': toHsl(getReadableForeground(accent)),
  }

  for (const [token, tokenColor] of ramp) {
    tokens[token] = toHsl(tokenColor)
  }

  return tokens
}

export function applyThemeColor(color: string, root?: HTMLElement | null) {
  const target = root ?? (typeof document === 'undefined' ? null : document.documentElement)
  const tokens = getThemeColorTokens(color)
  if (!target || !tokens) return

  for (const [token, value] of Object.entries(tokens)) {
    target.style.setProperty(token, value)
  }
}

export function clearThemeColor(root?: HTMLElement | null) {
  const target = root ?? (typeof document === 'undefined' ? null : document.documentElement)
  if (!target) return

  for (const token of THEME_COLOR_TOKEN_NAMES) {
    target.style.removeProperty(token)
  }
}

export function persistThemeAppearance(
  theme: SurfaceThemeKey,
  colorOverride: string | null,
  storage: StorageWriter | null = getClientStorage(),
  cookieTarget: ThemeCookieTarget | null = globalThis.document ?? null
) {
  const surfaceTheme = normalizeSurfaceTheme(theme)
  const normalizedColor = normalizeThemeColor(colorOverride)

  try {
    storage?.setItem(SURFACE_THEME_STORAGE_KEY, surfaceTheme)
    if (normalizedColor) storage?.setItem(THEME_COLOR_STORAGE_KEY, normalizedColor)
    else storage?.removeItem(THEME_COLOR_STORAGE_KEY)
  } catch {
    // Storage can be unavailable in private or policy-restricted browser contexts.
  }

  if (cookieTarget) {
    const commonAttributes = 'Path=/; Max-Age=31536000; SameSite=Lax'
    cookieTarget.cookie = `${SURFACE_THEME_COOKIE_KEY}=${surfaceTheme}; ${commonAttributes}`
    cookieTarget.cookie = normalizedColor
      ? `${THEME_COLOR_COOKIE_KEY}=${normalizedColor.slice(1)}; ${commonAttributes}`
      : `${THEME_COLOR_COOKIE_KEY}=; Path=/; Max-Age=0; SameSite=Lax`
  }

  return { surfaceTheme, colorOverride: normalizedColor }
}

export function notifyThemeAppearanceChanged(
  eventTarget: ThemeEventTarget | null = globalThis.window ?? null
) {
  const target = eventTarget
  if (!target) return

  const event =
    typeof CustomEvent === 'function'
      ? new CustomEvent(THEME_APPEARANCE_CHANGED_EVENT)
      : new Event(THEME_APPEARANCE_CHANGED_EVENT)
  target.dispatchEvent(event)
}

export function applyStoredThemeAppearance(
  storage: StorageReader | null = getClientStorage(),
  root?: HTMLElement | null,
  eventTarget?: ThemeEventTarget | null,
  options: ApplyThemeAppearanceOptions = {}
) {
  const effectiveStorage = storage
  const surfaceTheme = readSurfaceTheme(effectiveStorage)
  const colorOverride = readThemeColorOverride(effectiveStorage)
  const color = colorOverride ?? getSurfaceThemeMeta(surfaceTheme).defaultPrimary

  applySurfaceTheme(surfaceTheme, root)
  if (colorOverride) applyThemeColor(colorOverride, root)
  else clearThemeColor(root)

  if (options.notify !== false) {
    notifyThemeAppearanceChanged(eventTarget)
  }

  return { surfaceTheme, color, colorOverride }
}
