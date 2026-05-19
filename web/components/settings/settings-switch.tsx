'use client'

import { Switch, type SwitchProps } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

export function SettingsSwitch({ className, ...props }: Readonly<SwitchProps>) {
  return (
    <Switch
      className={cn(
        'h-6 w-11 border shadow-sm transition-[background-color,border-color,box-shadow]',
        'data-[state=checked]:border-blue-500 data-[state=checked]:bg-blue-600 data-[state=checked]:shadow-[0_8px_18px_rgba(37,99,235,0.22)]',
        'data-[state=unchecked]:border-slate-300 data-[state=unchecked]:bg-white data-[state=unchecked]:shadow-inner',
        'hover:data-[state=checked]:border-blue-600 hover:data-[state=checked]:bg-blue-700',
        'hover:data-[state=unchecked]:border-slate-400 hover:data-[state=unchecked]:bg-slate-50',
        'data-[state=checked]:[&>span]:bg-white data-[state=unchecked]:[&>span]:bg-slate-400',
        className
      )}
      {...props}
    />
  )
}
