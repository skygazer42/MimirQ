"use client"

import * as React from "react"
import { Check, Moon, Sun, Settings2, RefreshCw, Sparkles } from "lucide-react"
import { useTranslations } from 'next-intl'
import { useTheme } from "next-themes"

import { getClientStorage } from "@/lib/client-storage"
import { cn } from "@/lib/utils"
import {
  applySurfaceTheme,
  applyThemeColor,
  clearThemeColor,
  getSurfaceThemeMeta,
  notifyThemeAppearanceChanged,
  persistThemeAppearance,
  readSurfaceTheme,
  readThemeColorOverride,
  SURFACE_THEMES,
  type SurfaceThemeKey,
} from "@/lib/theme-surface"
import { IconButton } from "@/components/ui/icon-button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Label } from "@/components/ui/label"

const PRESET_COLORS = [
  { name: "Sky", value: "#0ea5e9" }, // Default
  { name: "Graphite", value: "#18181b" },
  { name: "Rose", value: "#e11d48" },
  { name: "Orange", value: "#ea580c" },
  { name: "Green", value: "#16a34a" },
  { name: "Violet", value: "#7c3aed" },
  { name: "Yellow", value: "#ca8a04" },
]

type ThemeCustomizerProps = {
  trigger?: React.ReactNode
}

export function ThemeCustomizer({ trigger }: Readonly<ThemeCustomizerProps> = {}) {
  const [mounted, setMounted] = React.useState(false)
  const t = useTranslations('CommonUi')
  const { theme, setTheme } = useTheme()
  const [colorOverride, setColorOverride] = React.useState<string | null>(null)
  const [surfaceTheme, setSurfaceTheme] = React.useState<SurfaceThemeKey>('ocean')
  const effectiveColor = colorOverride ?? getSurfaceThemeMeta(surfaceTheme).defaultPrimary
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
    const storage = getClientStorage()
    if (storage) {
      const nextSurfaceTheme = readSurfaceTheme(storage)
      setSurfaceTheme(nextSurfaceTheme)
      setColorOverride(readThemeColorOverride(storage))
    }
    setMounted(true)
  }, [])

  React.useEffect(() => {
    if (!mounted) return

    applySurfaceTheme(surfaceTheme)
    if (colorOverride) applyThemeColor(colorOverride)
    else clearThemeColor()
    if (globalThis.window !== undefined) {
      persistThemeAppearance(surfaceTheme, colorOverride)
      notifyThemeAppearanceChanged()
    }
  }, [colorOverride, mounted, surfaceTheme])

  if (!mounted) {
    return null
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        {triggerNode}
      </PopoverTrigger>
      <PopoverContent className="max-h-[calc(100dvh-2rem)] w-80 overflow-y-auto p-4" align="end" sideOffset={10}>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <h4 className="font-medium leading-none">{t('themeCustomizer.title')}</h4>
              <p className="text-xs text-muted-foreground">
                {t('themeCustomizer.description')}
              </p>
            </div>
            <IconButton
              label={t('themeCustomizer.resetAppearance')}
              variant="ghost"
              onClick={() => {
                setSurfaceTheme('ocean')
                setColorOverride(null)
              }}
            >
                <RefreshCw className="size-4" />
            </IconButton>
          </div>

          <div className="space-y-2">
            <Label className="text-xs">{t('themeCustomizer.surfaceLabel')}</Label>
            <div className="grid gap-2">
              {SURFACE_THEMES.map((preset) => (
                <button
                  key={preset.key}
                  type="button"
                  onClick={() => {
                    setSurfaceTheme(preset.key)
                    setColorOverride(null)
                  }}
                  className={cn(
                    'rounded-xl border px-3 py-3 text-left transition-colors duration-200 motion-reduce:transition-none',
                    surfaceTheme === preset.key
                      ? 'border-primary bg-primary/5 ring-2 ring-primary/15'
                      : 'border-border bg-card hover:border-primary/40 hover:bg-muted/60'
                  )}
                  aria-label={t('themeCustomizer.surfacePresetLabel', { name: preset.label })}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-foreground">{t(`themeCustomizer.surfacePresets.${preset.key}.title`)}</div>
                      <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
                        {t(`themeCustomizer.surfacePresets.${preset.key}.description`)}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <span
                        className="size-4 rounded-full border border-black/5"
                        style={{
                          backgroundColor:
                            preset.key === 'deepsea'
                              ? '#F7F9FF'
                              : preset.key === 'neutral'
                              ? '#FFFFFF'
                              : preset.key === 'classic'
                                ? '#F8F9FA'
                                : preset.key === 'earth'
                                  ? '#F5F0E8'
                                  : '#F7FBFC',
                        }}
                      />
                      <span
                        className="size-4 rounded-full border border-black/5"
                        style={{ backgroundColor: preset.defaultPrimary }}
                      />
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
          
          <div className="space-y-2">
            <Label className="text-xs">{t('themeCustomizer.colorLabel')}</Label>
            <div className="grid grid-cols-4 gap-2">
              <button
                type="button"
                onClick={() => setColorOverride(null)}
                aria-pressed={colorOverride === null}
                aria-label={t('themeCustomizer.useSurfaceColor')}
                title={t('themeCustomizer.useSurfaceColor')}
                className={cn(
                  "relative flex h-9 w-full items-center justify-center rounded-lg border border-border bg-card shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/45 hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 motion-reduce:transition-none motion-reduce:hover:translate-y-0",
                  colorOverride === null && "border-primary bg-primary/5 ring-2 ring-primary/25"
                )}
              >
                <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
                {colorOverride === null && (
                  <span className="absolute right-1 top-1 inline-flex size-3.5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
                    <Check className="size-2.5" aria-hidden="true" />
                    <span className="sr-only">{t('themeCustomizer.selected')}</span>
                  </span>
                )}
              </button>
              {PRESET_COLORS.map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  onClick={() => setColorOverride(preset.value)}
                  aria-pressed={colorOverride === preset.value}
                  aria-label={t('themeCustomizer.presetLabel', { name: preset.name })}
                  title={preset.name}
                  className={cn(
                    "relative flex h-9 w-full items-center justify-center rounded-lg border border-border bg-card shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/45 hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 motion-reduce:transition-none motion-reduce:hover:translate-y-0",
                    colorOverride === preset.value && "border-primary bg-primary/5 ring-2 ring-primary/25"
                  )}
                >
                  <span 
                    className="size-4 rounded-full border border-black/10 shadow-inner"
                    style={{ backgroundColor: preset.value }}
                  />
                  {colorOverride === preset.value && (
                    <span className="absolute right-1 top-1 inline-flex size-3.5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
                      <Check className="size-2.5" aria-hidden="true" />
                      <span className="sr-only">{t('themeCustomizer.selected')}</span>
                    </span>
                  )}
                </button>
              ))}
            </div>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {colorOverride
                ? t('themeCustomizer.customColorActive')
                : t('themeCustomizer.surfaceColorActive', { color: effectiveColor })}
            </p>
          </div>

          <div className="space-y-2">
            <Label className="text-xs">{t('themeCustomizer.modeLabel')}</Label>
            <div className="flex p-1 bg-muted rounded-lg">
                <button 
                    type="button"
                    onClick={() => setTheme('light')}
                    className={cn(
                        "flex-1 flex items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-colors duration-200 motion-reduce:transition-none",
                        theme === 'light' ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    )}
                >
                    <Sun className="h-3.5 w-3.5" /> {t('modeToggle.light')}
                </button>
                <button 
                    type="button"
                    onClick={() => setTheme('dark')}
                    className={cn(
                        "flex-1 flex items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-colors duration-200 motion-reduce:transition-none",
                        theme === 'dark' ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    )}
                >
                    <Moon className="h-3.5 w-3.5" /> {t('modeToggle.dark')}
                </button>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
