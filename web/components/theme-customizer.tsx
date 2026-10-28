"use client"

import * as React from "react"
import { Check, Monitor, Moon, Sun, Settings2, RotateCcw } from "@/components/icons"
import { useTranslations } from 'next-intl'
import { useTheme } from "next-themes"

import { getClientStorage } from "@/lib/client-storage"
import { cn } from "@/lib/utils"
import {
  applySurfaceTheme,
  applyThemeColor,
  clearThemeColor,
  notifyThemeAppearanceChanged,
  persistThemeAppearance,
  readSurfaceTheme,
  readThemeColorOverride,
  SURFACE_THEME_STORAGE_KEY,
  SURFACE_THEMES,
  THEME_APPEARANCE_CHANGED_EVENT,
  THEME_COLOR_STORAGE_KEY,
  type SurfaceThemeKey,
} from "@/lib/theme-surface"
import { IconButton } from "@/components/ui/icon-button"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"

const PRESET_COLORS = [
  { name: "sky", value: "#0ea5e9" },
  { name: "graphite", value: "#18181b" },
  { name: "rose", value: "#e11d48" },
  { name: "orange", value: "#ea580c" },
  { name: "green", value: "#16a34a" },
  { name: "violet", value: "#7c3aed" },
  { name: "yellow", value: "#ca8a04" },
] as const

const THEME_MODES = [
  { value: "light", Icon: Sun },
  { value: "dark", Icon: Moon },
  { value: "system", Icon: Monitor },
] as const

type ThemeCustomizerProps = {
  trigger?: React.ReactNode
}

export function ThemeCustomizer({ trigger }: Readonly<ThemeCustomizerProps> = {}) {
  const [mounted, setMounted] = React.useState(false)
  const t = useTranslations('CommonUi')
  const { theme, setTheme } = useTheme()
  const [colorOverride, setColorOverride] = React.useState<string | null>(null)
  const [surfaceTheme, setSurfaceTheme] = React.useState<SurfaceThemeKey>('ocean')
  const groupId = React.useId()
  const titleId = `${groupId}-title`
  const triggerNode = trigger ?? (
    <IconButton
      label={t('themeCustomizer.openLabel')}
      variant="outline"
      className="fixed bottom-4 right-4 z-50 size-12 rounded-full border-primary/20 bg-background/80 backdrop-blur-md shadow-lg hover:border-primary transition-colors duration-200 motion-reduce:transition-none supports-[padding:env(safe-area-inset-bottom)]:bottom-[calc(env(safe-area-inset-bottom)+1rem)] supports-[padding:env(safe-area-inset-right)]:right-[calc(env(safe-area-inset-right)+1rem)]"
    >
      <Settings2 className="size-6 text-primary" />
    </IconButton>
  )

  React.useEffect(() => {
    const syncStoredAppearance = () => {
      const storage = getClientStorage()
      if (!storage) return
      setSurfaceTheme(readSurfaceTheme(storage))
      setColorOverride(readThemeColorOverride(storage))
    }
    const handleStorage = (event: StorageEvent) => {
      if (event.key && event.key !== SURFACE_THEME_STORAGE_KEY && event.key !== THEME_COLOR_STORAGE_KEY) return
      syncStoredAppearance()
    }

    syncStoredAppearance()
    setMounted(true)
    window.addEventListener('storage', handleStorage)
    window.addEventListener(THEME_APPEARANCE_CHANGED_EVENT, syncStoredAppearance)

    return () => {
      window.removeEventListener('storage', handleStorage)
      window.removeEventListener(THEME_APPEARANCE_CHANGED_EVENT, syncStoredAppearance)
    }
  }, [])

  const updateAppearance = (nextSurfaceTheme: SurfaceThemeKey, nextColorOverride: string | null) => {
    setSurfaceTheme(nextSurfaceTheme)
    setColorOverride(nextColorOverride)
    applySurfaceTheme(nextSurfaceTheme)
    if (nextColorOverride) applyThemeColor(nextColorOverride)
    else clearThemeColor()
    // Only user changes persist; syncing another tab must not write stale values back.
    persistThemeAppearance(nextSurfaceTheme, nextColorOverride)
    notifyThemeAppearanceChanged()
  }

  if (!mounted) {
    return null
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        {triggerNode}
      </PopoverTrigger>
      <PopoverContent
        aria-labelledby={titleId}
        align="end"
        side="top"
        sideOffset={8}
        collisionPadding={12}
        className="flex max-h-[min(calc(100dvh-1.5rem),var(--radix-popover-content-available-height))] w-80 max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-xl p-0"
      >
        <div className="flex shrink-0 items-center justify-between gap-3 px-4 py-2">
          <h2 id={titleId} className="text-base font-medium leading-6">{t('themeCustomizer.title')}</h2>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-11 gap-1.5 px-2 text-sm font-normal text-muted-foreground shadow-none hover:bg-muted hover:text-foreground sm:h-10"
            aria-label={t('themeCustomizer.resetAppearance')}
            title={t('themeCustomizer.resetAppearance')}
            onClick={() => updateAppearance('ocean', null)}
          >
            <RotateCcw className="size-3.5" aria-hidden="true" />
            {t('themeCustomizer.resetLabel')}
          </Button>
        </div>

        <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-4 pb-4">
          <fieldset>
            <legend className="mb-2 text-sm font-medium">{t('themeCustomizer.surfaceLabel')}</legend>
            {SURFACE_THEMES.map((preset) => (
              <label
                key={preset.key}
                className={cn(
                  'relative flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 text-sm transition-colors duration-150 hover:bg-muted/60 motion-reduce:transition-none sm:min-h-10',
                  surfaceTheme === preset.key && 'bg-muted font-medium'
                )}
              >
                <input
                  type="radio"
                  name={`${groupId}-surface`}
                  value={preset.key}
                  checked={surfaceTheme === preset.key}
                  onChange={() => updateAppearance(preset.key, null)}
                  aria-label={t('themeCustomizer.surfacePresetLabel', { name: t(`themeCustomizer.surfacePresets.${preset.key}.title`) })}
                  aria-describedby={`${groupId}-${preset.key}-hint`}
                  className="peer sr-only"
                />
                <span className="pointer-events-none absolute inset-0 rounded-lg peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-popover" aria-hidden="true" />
                <span
                  className="flex h-7 w-12 shrink-0 items-center gap-1 rounded-md border border-foreground/15 px-1.5"
                  style={{ backgroundColor: preset.previewSurface }}
                  aria-hidden="true"
                >
                  <span className="size-2.5 shrink-0 rounded-sm" style={{ backgroundColor: preset.defaultPrimary }} />
                  <span className="flex flex-1 flex-col gap-1">
                    <span className="h-0.5 rounded-full" style={{ backgroundColor: preset.defaultPrimary, opacity: 0.55 }} />
                    <span className="h-0.5 w-2/3 rounded-full" style={{ backgroundColor: preset.defaultPrimary, opacity: 0.3 }} />
                  </span>
                </span>
                <span className="flex-1">{t(`themeCustomizer.surfacePresets.${preset.key}.title`)}</span>
                <span id={`${groupId}-${preset.key}-hint`} className="sr-only">{t(`themeCustomizer.surfacePresets.${preset.key}.description`)}</span>
                <Check className={cn('size-4 shrink-0', surfaceTheme === preset.key ? 'opacity-100' : 'opacity-0')} aria-hidden="true" />
              </label>
            ))}
          </fieldset>

          <fieldset>
            <legend className="mb-2 text-sm font-medium">{t('themeCustomizer.colorLabel')}</legend>
            <div className="grid grid-cols-4 gap-1">
              <label className="relative flex min-h-11 cursor-pointer items-center justify-center gap-1 rounded-lg text-sm hover:bg-muted/60 sm:min-h-10">
                <input
                  type="radio"
                  name={`${groupId}-accent`}
                  value="auto"
                  checked={colorOverride === null}
                  onChange={() => updateAppearance(surfaceTheme, null)}
                  aria-label={t('themeCustomizer.useSurfaceColor')}
                  className="peer sr-only"
                />
                <span className="pointer-events-none absolute inset-0 rounded-lg peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-popover" aria-hidden="true" />
                <Check className={cn('size-3.5', colorOverride === null ? 'opacity-100' : 'opacity-0')} aria-hidden="true" />
                {t('themeCustomizer.autoColor')}
              </label>
              {PRESET_COLORS.map((preset) => (
                <label
                  key={preset.name}
                  title={t(`themeCustomizer.colors.${preset.name}`)}
                  className="relative flex min-h-11 cursor-pointer items-center justify-center rounded-lg transition-colors duration-150 hover:bg-muted/60 motion-reduce:transition-none sm:min-h-10"
                >
                  <input
                    type="radio"
                    name={`${groupId}-accent`}
                    value={preset.value}
                    checked={colorOverride === preset.value}
                    onChange={() => updateAppearance(surfaceTheme, preset.value)}
                    aria-label={t('themeCustomizer.presetLabel', { name: t(`themeCustomizer.colors.${preset.name}`) })}
                    className="peer sr-only"
                  />
                  <span className="pointer-events-none absolute inset-0 rounded-lg peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-popover" aria-hidden="true" />
                  <span
                    className={cn(
                      'flex size-6 items-center justify-center rounded-full border border-foreground/10 text-primary-foreground',
                      colorOverride === preset.value && 'ring-2 ring-foreground/70 ring-offset-2 ring-offset-popover'
                    )}
                    style={{ backgroundColor: preset.value }}
                    aria-hidden="true"
                  >
                    {colorOverride === preset.value ? <Check className="size-3.5" /> : null}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="mb-2 text-sm font-medium">{t('themeCustomizer.modeLabel')}</legend>
            <div className="grid grid-cols-3 rounded-lg bg-muted p-1">
              {THEME_MODES.map(({ value, Icon }) => (
                <label
                  key={value}
                  className={cn(
                    'relative flex min-h-11 cursor-pointer items-center justify-center gap-1 rounded-md px-0.5 text-sm transition-[background-color,color,box-shadow] duration-150 motion-reduce:transition-none sm:min-h-10',
                    theme === value ? 'bg-popover text-foreground shadow-subtle' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <input
                    type="radio"
                    name={`${groupId}-mode`}
                    value={value}
                    checked={theme === value}
                    onChange={() => setTheme(value)}
                    aria-label={t(`modeToggle.${value}`)}
                    className="peer sr-only"
                  />
                  <span className="pointer-events-none absolute inset-0 rounded-md peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-popover" aria-hidden="true" />
                  <Icon className="size-3.5 shrink-0" aria-hidden="true" />
                  <span className="whitespace-nowrap">{t(`modeToggle.${value}`)}</span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      </PopoverContent>
    </Popover>
  )
}
