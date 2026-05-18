'use client'

import { Switch, type SwitchProps } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

export function SettingsSwitch({ className, ...props }: Readonly<SwitchProps>) {
  return (
    <Switch
      className={cn(
        'h-6 w-11 border border-slate-200 shadow-sm',
        'data-[state=checked]:border-blue-600 data-[state=checked]:bg-blue-600',
        'data-[state=unchecked]:border-slate-200 data-[state=unchecked]:bg-slate-300',
        'hover:data-[state=checked]:bg-blue-700 hover:data-[state=unchecked]:bg-slate-400',
        className
      )}
      {...props}
    />
  )
}
