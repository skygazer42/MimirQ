'use client'

import { Switch, type SwitchProps } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

type SettingsSwitchIndicatorProps = {
  readonly checked: boolean
  readonly className?: string
}

const SETTINGS_SWITCH_TRACK =
  'relative inline-flex h-[1.875rem] w-20 shrink-0 items-center overflow-hidden rounded-full border shadow-sm transition-[background-color,border-color,box-shadow,transform] duration-150'

const SETTINGS_SWITCH_STATE =
  "[--switch-translate-checked:2.5rem] [--switch-translate-unchecked:0.25rem] before:pointer-events-none before:absolute before:left-2.5 before:top-1/2 before:z-20 before:-translate-y-1/2 before:text-[10px] before:font-semibold before:leading-none before:tracking-[0.04em] before:content-['停用'] before:transition-colors before:duration-150 after:pointer-events-none after:absolute after:right-2.5 after:top-1/2 after:z-20 after:-translate-y-1/2 after:text-[10px] after:font-semibold after:leading-none after:tracking-[0.04em] after:content-['启用'] after:transition-colors after:duration-150 data-[switch-state=checked]:before:text-muted-foreground/65 data-[switch-state=checked]:after:text-primary-foreground data-[switch-state=unchecked]:before:text-foreground/80 data-[switch-state=unchecked]:after:text-muted-foreground/65"

const SETTINGS_SWITCH_TONE =
  'bg-muted/70 ring-1 ring-border/70 data-[switch-state=checked]:border-primary/45 data-[switch-state=checked]:bg-primary/15 data-[switch-state=checked]:shadow-[0_8px_18px_hsl(var(--primary)/0.14)] data-[switch-state=unchecked]:border-border data-[switch-state=unchecked]:bg-muted/65 data-[switch-state=unchecked]:shadow-inner hover:data-[switch-state=checked]:border-primary/60 hover:data-[switch-state=unchecked]:border-muted-foreground/35'

const SETTINGS_SWITCH_THUMB =
  '[&>span]:relative [&>span]:z-10 [&>span]:h-[1.375rem] [&>span]:w-9 [&>span]:rounded-full [&>span]:border [&>span]:transition-transform data-[switch-state=checked]:[&>span]:border-primary data-[switch-state=checked]:[&>span]:bg-gradient-to-r data-[switch-state=checked]:[&>span]:from-primary data-[switch-state=checked]:[&>span]:to-accent data-[switch-state=checked]:[&>span]:shadow-[0_6px_14px_hsl(var(--primary)/0.28)] data-[switch-state=unchecked]:[&>span]:border-background data-[switch-state=unchecked]:[&>span]:bg-background data-[switch-state=unchecked]:[&>span]:shadow-[0_4px_10px_hsl(var(--foreground)/0.12)]'

export function SettingsSwitchIndicator({
  checked,
  className,
}: Readonly<SettingsSwitchIndicatorProps>) {
  return (
    <span
      aria-hidden="true"
      data-state={checked ? 'checked' : 'unchecked'}
      data-switch-state={checked ? 'checked' : 'unchecked'}
      className={cn(
        SETTINGS_SWITCH_TRACK,
        SETTINGS_SWITCH_STATE,
        SETTINGS_SWITCH_TONE,
        SETTINGS_SWITCH_THUMB,
        'pointer-events-none',
        className
      )}
    >
      <span
        data-state={checked ? 'checked' : 'unchecked'}
        data-switch-state={checked ? 'checked' : 'unchecked'}
        className={cn(
          'pointer-events-none block h-5 w-5 rounded-full bg-background shadow-md ring-0 transition-all duration-150',
          checked
            ? 'translate-x-[var(--switch-translate-checked,2.5rem)] scale-[1.02]'
            : 'translate-x-[var(--switch-translate-unchecked,0.25rem)]'
        )}
      />
    </span>
  )
}

export function SettingsSwitch({ className, ...props }: Readonly<SwitchProps>) {
  return (
    <Switch
      className={cn(
        SETTINGS_SWITCH_TRACK,
        SETTINGS_SWITCH_STATE,
        SETTINGS_SWITCH_TONE,
        SETTINGS_SWITCH_THUMB,
        className
      )}
      {...props}
    />
  )
}
