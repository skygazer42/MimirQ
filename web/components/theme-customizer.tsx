'use client'

import { useEffect, useId, useState, type ReactElement } from 'react'
import { Check, ChevronLeft, Monitor, Moon, Sun, RotateCcw } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { useTheme } from 'next-themes'

import { cn } from '@/lib/utils'
import {
  applySurfaceTheme,
  applyThemeColor,
  clearThemeColor,
  getSurfaceThemeMeta,
  normalizeSurfaceTheme,
  normalizeThemeColorCookie,
  notifyThemeAppearanceChanged,
  persistThemeAppearance,
  SURFACE_THEMES,
  THEME_ACCENT_COLORS,
  THEME_APPEARANCE_CHANGED_EVENT,
  type SurfaceThemeKey,
} from '@/lib/theme-surface'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

const THEME_MODES = [
  { value: 'light', Icon: Sun },
  { value: 'dark', Icon: Moon },
  { value: 'system', Icon: Monitor },
] as const

export function ThemeAppearancePanel({ onBack }: Readonly<{ onBack?: () => void }>) {
  const t = useTranslations('CommonUi')
  const { theme, setTheme } = useTheme()
  const [appearance, setAppearance] = useState<{ surfaceTheme: SurfaceThemeKey; colorOverride: string | null } | null>(
    null,
  )
  const groupId = useId()
  const titleId = `${groupId}-title`

  useEffect(() => {
    const syncAppliedAppearance = () => {
      const { dataset } = document.documentElement
      setAppearance({
        surfaceTheme: normalizeSurfaceTheme(dataset.surfaceTheme),
        colorOverride: normalizeThemeColorCookie(dataset.themeColor),
      })
    }
    syncAppliedAppearance()
    window.addEventListener(THEME_APPEARANCE_CHANGED_EVENT, syncAppliedAppearance)
    return () => window.removeEventListener(THEME_APPEARANCE_CHANGED_EVENT, syncAppliedAppearance)
  }, [])

  const updateAppearance = (nextSurface: SurfaceThemeKey, nextColor: string | null) => {
    applySurfaceTheme(nextSurface)
    if (nextColor === null) clearThemeColor()
    else applyThemeColor(nextColor)
    notifyThemeAppearanceChanged()
    persistThemeAppearance(nextSurface, nextColor)
  }

  if (appearance === null) return null

  const { surfaceTheme, colorOverride } = appearance
  const defaultPrimary = getSurfaceThemeMeta(surfaceTheme).defaultPrimary
  return (
    <section aria-labelledby={titleId} className="flex min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <div className="flex min-w-0 items-center gap-1">
          {onBack !== undefined && (
            <Button
              type="button"
              autoFocus
              variant="ghost"
              size="icon"
              className="size-10"
              aria-label={t('themeCustomizer.backToAccount')}
              onClick={onBack}
            >
              <ChevronLeft className="size-4" />
            </Button>
          )}
          <h2 id={titleId} className="text-sm font-medium">
            {t('themeCustomizer.title')}
          </h2>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-10 gap-1.5 px-2 text-xs font-normal text-muted-foreground"
          aria-label={t('themeCustomizer.resetAppearance')}
          onClick={() => {
            setTheme('system')
            updateAppearance('ocean', null)
          }}
        >
          <RotateCcw className="size-3.5" aria-hidden="true" />
          {t('themeCustomizer.resetLabel')}
        </Button>
      </div>
      <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain p-4">
        <fieldset>
          <legend className="mb-2 text-xs font-medium text-muted-foreground">{t('themeCustomizer.modeLabel')}</legend>
          <div className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
            {THEME_MODES.map(({ value, Icon }) => (
              <label
                key={value}
                className={cn(
                  'relative flex min-h-11 cursor-pointer items-center justify-center gap-1 rounded-md text-xs',
                  theme === value ? 'bg-popover text-foreground shadow-subtle' : 'text-muted-foreground',
                )}
              >
                <input
                  type="radio"
                  name={`${groupId}-mode`}
                  value={value}
                  checked={theme === value}
                  onChange={() => setTheme(value)}
                  className="peer sr-only"
                />
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 rounded-md peer-focus-visible:ring-2 peer-focus-visible:ring-ring"
                />
                <Icon className="size-3.5" aria-hidden="true" />
                <span>{t(`modeToggle.${value}`)}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-2 text-xs font-medium text-muted-foreground">
            {t('themeCustomizer.surfaceLabel')}
          </legend>
          <div className="grid grid-cols-2 gap-2">
            {SURFACE_THEMES.map((preset) => (
              <label
                key={preset.key}
                className={cn(
                  'relative flex min-h-14 cursor-pointer items-center gap-2 rounded-lg border p-2 text-xs',
                  surfaceTheme === preset.key
                    ? 'border-ring/60 bg-muted/50 font-medium'
                    : 'border-border/60 hover:bg-muted/40',
                )}
              >
                <input
                  type="radio"
                  name={`${groupId}-surface`}
                  value={preset.key}
                  checked={surfaceTheme === preset.key}
                  onChange={() => updateAppearance(preset.key, colorOverride)}
                  aria-labelledby={`${groupId}-${preset.key}-title`}
                  aria-describedby={`${groupId}-${preset.key}-hint`}
                  className="peer sr-only"
                />
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 rounded-lg peer-focus-visible:ring-2 peer-focus-visible:ring-ring"
                />
                <span
                  aria-hidden="true"
                  className="flex h-7 w-10 shrink-0 flex-col justify-center gap-1 rounded border border-black/10 px-1.5"
                  style={{ backgroundColor: preset.previewSurface }}
                >
                  <span className="h-1 rounded bg-neutral-400/70" />
                  <span className="h-0.5 w-2/3 rounded bg-neutral-400/50" />
                </span>
                <span id={`${groupId}-${preset.key}-title`} className="min-w-0 flex-1">
                  {t(`themeCustomizer.surfacePresets.${preset.key}.title`)}
                </span>
                <span id={`${groupId}-${preset.key}-hint`} className="sr-only">
                  {t(`themeCustomizer.surfacePresets.${preset.key}.description`)}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-2 text-xs font-medium text-muted-foreground">{t('themeCustomizer.colorLabel')}</legend>
          <div className="grid grid-cols-3 gap-2">
            <label
              title={t('themeCustomizer.useSurfaceColor')}
              className="relative flex min-h-14 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg hover:bg-muted/40"
            >
              <input
                type="radio"
                name={`${groupId}-accent`}
                value="auto"
                checked={colorOverride === null}
                onChange={() => updateAppearance(surfaceTheme, null)}
                className="peer sr-only"
              />
              <span
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 rounded-lg peer-focus-visible:ring-2 peer-focus-visible:ring-ring"
              />
              <span
                aria-hidden="true"
                className={cn(
                  'grid size-6 place-items-center rounded-full',
                  colorOverride === null && 'outline-2 outline-offset-2 outline-ring',
                )}
                style={{ background: `linear-gradient(135deg, ${defaultPrimary} 50%, #c85a32 50%)` }}
              >
                {colorOverride === null && (
                  <Check className="size-4 rounded-full bg-foreground p-0.5 text-background stroke-[2.5]" />
                )}
              </span>
              <span className="text-[11px] text-muted-foreground">{t('themeCustomizer.autoColor')}</span>
            </label>
            {THEME_ACCENT_COLORS.map((preset) => (
              <label
                key={preset.name}
                className="relative flex min-h-14 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg hover:bg-muted/40"
              >
                <input
                  type="radio"
                  name={`${groupId}-accent`}
                  value={preset.value}
                  checked={colorOverride === preset.value}
                  onChange={() => updateAppearance(surfaceTheme, preset.value)}
                  className="peer sr-only"
                />
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 rounded-lg peer-focus-visible:ring-2 peer-focus-visible:ring-ring"
                />
                <span
                  aria-hidden="true"
                  className={cn(
                    'grid size-6 place-items-center rounded-full',
                    colorOverride === preset.value && 'outline-2 outline-offset-2',
                  )}
                  style={{ backgroundColor: preset.value, outlineColor: preset.value }}
                >
                  {colorOverride === preset.value && (
                    <Check className="size-4 rounded-full bg-foreground p-0.5 text-background stroke-[2.5]" />
                  )}
                </span>
                <span className="text-[11px] text-muted-foreground">{t(`themeCustomizer.colors.${preset.name}`)}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
    </section>
  )
}

export function ThemeCustomizer({ trigger }: Readonly<{ trigger: ReactElement }>) {
  const t = useTranslations('CommonUi')
  return (
    <Popover>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        aria-label={t('themeCustomizer.title')}
        align="end"
        side="top"
        sideOffset={8}
        collisionPadding={12}
        className="flex max-h-[min(32rem,var(--radix-popover-content-available-height))] w-80 max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-xl p-0"
      >
        <ThemeAppearancePanel />
      </PopoverContent>
    </Popover>
  )
}
