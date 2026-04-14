export type SurfaceThemeKey = 'ocean' | 'classic' | 'earth'

export const SURFACE_THEME_STORAGE_KEY = 'mimirq.surfaceTheme'
export const THEME_COLOR_STORAGE_KEY = 'mimirq.themeColor'

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

export function readSurfaceTheme(storage?: Pick<Storage, 'getItem'> | null): SurfaceThemeKey {
  return normalizeSurfaceTheme(storage?.getItem(SURFACE_THEME_STORAGE_KEY))
}

export function applySurfaceTheme(theme: SurfaceThemeKey, root?: HTMLElement | null) {
  const target = root || (typeof document !== 'undefined' ? document.documentElement : null)
  if (!target) return
  target.dataset.surfaceTheme = normalizeSurfaceTheme(theme)
}
