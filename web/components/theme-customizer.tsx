"use client"

import * as React from "react"
import { Moon, Sun, Settings2, RefreshCw } from "lucide-react"
import { useTranslations } from 'next-intl'
import { useTheme } from "next-themes"
import chroma from "chroma-js"

import { cn } from "@/lib/utils"
import { IconButton } from "@/components/ui/icon-button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Label } from "@/components/ui/label"

const PRESET_COLORS = [
  { name: "Sky", value: "#0ea5e9" }, // Default
  { name: "Zinc", value: "#52525b" },
  { name: "Rose", value: "#e11d48" },
  { name: "Orange", value: "#ea580c" },
  { name: "Green", value: "#16a34a" },
  { name: "Violet", value: "#7c3aed" },
  { name: "Yellow", value: "#ca8a04" },
]

export function ThemeCustomizer() {
  const [mounted, setMounted] = React.useState(false)
  const t = useTranslations('CommonUi')
  const { theme, setTheme } = useTheme()
  const [color, setColor] = React.useState(PRESET_COLORS[0].value)

  React.useEffect(() => {
    setMounted(true)
  }, [])

  // Apply theme color
  React.useEffect(() => {
    const root = document.documentElement
    
    // Generate palette
    // Primary: The selected color
    const primary = chroma(color)
    
    // Convert to HSL for Tailwind
    const toHsl = (c: any) => {
        const [h, s, l] = c.hsl()
        return `${isNaN(h) ? 0 : h.toFixed(1)} ${(s * 100).toFixed(1)}% ${(l * 100).toFixed(1)}%`
    }

    root.style.setProperty("--primary", toHsl(primary))
    root.style.setProperty("--ring", toHsl(primary.alpha(0.5)))
    
    // We could generate more derived colors here if needed
    // e.g. --primary-foreground based on contrast
    const fg = chroma.contrast(primary, 'white') > 4.5 ? 'white' : 'black'
    root.style.setProperty("--primary-foreground", toHsl(chroma(fg)))

  }, [color])

  if (!mounted) {
    return null
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <IconButton
          label={t('themeCustomizer.openLabel')}
          variant="outline"
          className="fixed bottom-4 right-4 z-50 size-12 rounded-full border-primary/20 bg-background/80 backdrop-blur-md shadow-lg hover:border-primary transition-colors duration-200 motion-reduce:transition-none supports-[padding:env(safe-area-inset-bottom)]:bottom-[calc(env(safe-area-inset-bottom)+1rem)] supports-[padding:env(safe-area-inset-right)]:right-[calc(env(safe-area-inset-right)+1rem)]"
        >
          <Settings2 className="h-6 w-6 text-primary" />
        </IconButton>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-4" align="end" sideOffset={10}>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <h4 className="font-medium leading-none">{t('themeCustomizer.title')}</h4>
              <p className="text-xs text-muted-foreground">
                {t('themeCustomizer.description')}
              </p>
            </div>
            <IconButton
              label={t('themeCustomizer.resetColor')}
              variant="ghost"
              onClick={() => setColor(PRESET_COLORS[0].value)}
            >
                <RefreshCw className="h-4 w-4" />
            </IconButton>
          </div>
          
          <div className="space-y-2">
            <Label className="text-xs">{t('themeCustomizer.colorLabel')}</Label>
            <div className="grid grid-cols-4 gap-2">
              {PRESET_COLORS.map((preset) => (
                <button
                  key={preset.name}
                  onClick={() => setColor(preset.value)}
                  aria-label={t('themeCustomizer.presetLabel', { name: preset.name })}
                  title={preset.name}
                  className={cn(
                    "flex h-8 w-full items-center justify-center rounded-md border border-muted bg-popover hover:bg-accent hover:text-accent-foreground transition-colors duration-200 motion-reduce:transition-none",
                    color === preset.value && "border-primary ring-2 ring-primary/20"
                  )}
                >
                  <span 
                    className="h-4 w-4 rounded-full" 
                    style={{ backgroundColor: preset.value }}
                  />
                  {color === preset.value && (
                      <span className="sr-only">{t('themeCustomizer.selected')}</span>
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-xs">{t('themeCustomizer.modeLabel')}</Label>
            <div className="flex p-1 bg-muted rounded-lg">
                <button 
                    onClick={() => setTheme('light')}
                    className={cn(
                        "flex-1 flex items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-colors duration-200 motion-reduce:transition-none",
                        theme === 'light' ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    )}
                >
                    <Sun className="h-3.5 w-3.5" /> {t('modeToggle.light')}
                </button>
                <button 
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
