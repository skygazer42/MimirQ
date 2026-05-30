import chroma, { type Color } from 'chroma-js'

export type SurfaceThemeKey = 'ocean' | 'classic' | 'earth'

export const SURFACE_THEME_STORAGE_KEY = 'mimirq.surfaceTheme'
export const THEME_COLOR_STORAGE_KEY = 'mimirq.themeColor'
export const THEME_APPEARANCE_CHANGED_EVENT = 'mimirq:theme-appearance-changed'

type StorageReader = Pick<Storage, 'getItem'>
type ThemeEventTarget = Pick<Window, 'dispatchEvent'>

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
    defaultPrimary: '#0ea5e9',
  },
  {
    key: 'classic',
    label: 'Classic',
    description: '经典白灰，浅灰白背景配深灰正文与蓝色强调。',
    defaultPrimary: '#007BFF',
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
  if (raw === 'classic' || raw === 'earth') return raw
  return 'ocean'
}

export function getSurfaceThemeMeta(theme: SurfaceThemeKey) {
  return SURFACE_THEMES.find((item) => item.key === theme) || SURFACE_THEMES[0]
}

export function readSurfaceTheme(storage?: StorageReader | null): SurfaceThemeKey {
  return normalizeSurfaceTheme(storage?.getItem(SURFACE_THEME_STORAGE_KEY))
}

export function applySurfaceTheme(theme: SurfaceThemeKey, root?: HTMLElement | null) {
  const target = root || (typeof document !== 'undefined' ? document.documentElement : null)
  if (!target) return
  target.dataset.surfaceTheme = normalizeSurfaceTheme(theme)
}

function toHsl(color: Color): string {
  const [hue, saturation, lightness] = color.hsl()
  const safeHue = Number.isFinite(hue) ? hue : 0

  return `${safeHue.toFixed(1)} ${(saturation * 100).toFixed(1)}% ${(lightness * 100).toFixed(1)}%`
}

function setColorToken(target: HTMLElement, name: string, color: Color) {
  target.style.setProperty(name, toHsl(color))
}

function getReadableForeground(color: Color): Color {
  const lightness = color.get('hsl.l')

  if (Number.isFinite(lightness) && lightness <= 0.72) {
    return chroma('white')
  }

  return chroma.contrast(color, 'white') > 4.5 ? chroma('white') : chroma('black')
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

export function applyThemeColor(color: string, root?: HTMLElement | null) {
  const target = root || (typeof document !== 'undefined' ? document.documentElement : null)
  if (!target || !chroma.valid(color)) return

  const primary = chroma(color)
  const foreground = getReadableForeground(primary)
  const primaryHue = primary.get('hsl.h')
  const accentHue = Number.isFinite(primaryHue) ? (primaryHue + 26) % 360 : 211
  const accent = primary.set('hsl.h', accentHue).saturate(0.35)
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

  setColorToken(target, '--primary', primary)
  setColorToken(target, '--ring', primary)
  setColorToken(target, '--primary-foreground', foreground)
  setColorToken(target, '--info', primary)
  setColorToken(target, '--info-foreground', foreground)
  setColorToken(target, '--accent', accent)
  setColorToken(target, '--accent-foreground', getReadableForeground(accent))

  for (const [token, tokenColor] of ramp) {
    setColorToken(target, token, tokenColor)
  }
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
  storage: StorageReader | null = globalThis.window?.localStorage ?? null,
  root?: HTMLElement | null,
  eventTarget?: ThemeEventTarget | null,
  options: ApplyThemeAppearanceOptions = {}
) {
  const effectiveStorage = storage
  const surfaceTheme = readSurfaceTheme(effectiveStorage)
  const color = readThemeColor(effectiveStorage, surfaceTheme)

  applySurfaceTheme(surfaceTheme, root)
  applyThemeColor(color, root)

  if (options.notify !== false) {
    notifyThemeAppearanceChanged(eventTarget)
  }

  return { surfaceTheme, color }
}
