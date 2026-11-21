import { getClientStorage } from './client-storage'

export type SurfaceThemeKey = keyof typeof SURFACE_THEME_PRESETS

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

const SURFACE_THEME_PRESETS = {
  ocean: {
    key: 'ocean',
    previewSurface: '#faf9f7',
    defaultPrimary: '#20262e',
  },
  neutral: {
    key: 'neutral',
    previewSurface: '#ffffff',
    defaultPrimary: '#20262e',
  },
  classic: {
    key: 'classic',
    previewSurface: '#f6f7f8',
    defaultPrimary: '#20262e',
  },
  earth: {
    key: 'earth',
    previewSurface: '#f5f0e8',
    defaultPrimary: '#20262e',
  },
} as const

export const SURFACE_THEMES = Object.values(SURFACE_THEME_PRESETS)

export const THEME_ACCENT_COLORS = [
  { name: 'terracotta', value: '#c85a32' },
  { name: 'sky', value: '#0284c7' },
  { name: 'indigo', value: '#4f46e5' },
  { name: 'violet', value: '#7c3aed' },
  { name: 'graphite', value: '#18181b' },
] as const

export function normalizeSurfaceTheme(value?: string | null): SurfaceThemeKey {
  const candidate = value?.trim().toLowerCase()
  return SURFACE_THEMES.find((preset) => preset.key === candidate)?.key ?? 'ocean'
}

export function getSurfaceThemeMeta(theme: SurfaceThemeKey) {
  return SURFACE_THEME_PRESETS[theme]
}

export function applySurfaceTheme(theme: SurfaceThemeKey, root?: HTMLElement | null) {
  const target = root ?? (typeof document === 'undefined' ? null : document.documentElement)
  if (!target) return
  target.dataset.surfaceTheme = theme
}

export function normalizeThemeColor(value?: string | null): string | null {
  const color = value?.trim().toLowerCase()
  const preset = THEME_ACCENT_COLORS.find((item) => item.value === color)
  return preset === undefined ? null : preset.value
}

export function normalizeThemeColorCookie(value?: string | null): string | null {
  const candidate = value?.trim()
  if (candidate === undefined) return null
  return normalizeThemeColor(`#${candidate}`)
}

export function readThemeColorOverride(storage?: StorageReader | null): string | null {
  return normalizeThemeColor(storage?.getItem(THEME_COLOR_STORAGE_KEY))
}

export function applyThemeColor(color: string, root?: HTMLElement | null) {
  const target = root ?? (typeof document === 'undefined' ? null : document.documentElement)
  const normalized = normalizeThemeColor(color)
  if (target === null || normalized === null) return

  clearThemeColor(target)

  target.dataset.themeColor = normalized.slice(1)
}

export function clearThemeColor(root?: HTMLElement | null) {
  const target = root ?? (typeof document === 'undefined' ? null : document.documentElement)
  if (!target) return

  delete target.dataset.themeColor
  for (const token of THEME_COLOR_TOKEN_NAMES) {
    target.style.removeProperty(token)
  }
}

export function persistThemeAppearance(
  theme: SurfaceThemeKey,
  colorOverride: string | null,
  storage: StorageWriter | null = getClientStorage(),
  cookieTarget: ThemeCookieTarget | null = globalThis.document ?? null,
) {
  const normalizedColor = normalizeThemeColor(colorOverride)

  try {
    storage?.setItem(SURFACE_THEME_STORAGE_KEY, theme)
    if (normalizedColor !== null) storage?.setItem(THEME_COLOR_STORAGE_KEY, normalizedColor)
    else storage?.removeItem(THEME_COLOR_STORAGE_KEY)
  } catch {
    // Storage can be unavailable in private or policy-restricted browser contexts.
  }

  if (cookieTarget) {
    const commonAttributes = 'Path=/; Max-Age=31536000; SameSite=Lax'
    cookieTarget.cookie = `${SURFACE_THEME_COOKIE_KEY}=${theme}; ${commonAttributes}`
    cookieTarget.cookie =
      normalizedColor === null
        ? `${THEME_COLOR_COOKIE_KEY}=; Path=/; Max-Age=0; SameSite=Lax`
        : `${THEME_COLOR_COOKIE_KEY}=${normalizedColor.slice(1)}; ${commonAttributes}`
  }

  return { surfaceTheme: theme, colorOverride: normalizedColor }
}

export function notifyThemeAppearanceChanged(eventTarget: ThemeEventTarget | null = globalThis.window ?? null) {
  if (eventTarget === null) return
  eventTarget.dispatchEvent(new Event(THEME_APPEARANCE_CHANGED_EVENT))
}

export function applyStoredThemeAppearance(
  storage: StorageReader | null = getClientStorage(),
  root?: HTMLElement | null,
  eventTarget?: ThemeEventTarget | null,
  options: ApplyThemeAppearanceOptions = {},
) {
  const surfaceTheme = normalizeSurfaceTheme(storage?.getItem(SURFACE_THEME_STORAGE_KEY))
  const colorOverride = readThemeColorOverride(storage)
  const color = colorOverride ?? getSurfaceThemeMeta(surfaceTheme).defaultPrimary

  applySurfaceTheme(surfaceTheme, root)
  if (colorOverride !== null) applyThemeColor(colorOverride, root)
  else clearThemeColor(root)

  if (options.notify !== false) {
    notifyThemeAppearanceChanged(eventTarget)
  }

  return { surfaceTheme, color, colorOverride }
}
