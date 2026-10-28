'use client'

import { Switch, type SwitchProps } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

type SettingsSwitchIndicatorProps = { readonly checked: boolean; readonly className?: string }

export function SettingsSwitchIndicator({ checked, className }: Readonly<SettingsSwitchIndicatorProps>) {
  return (
    <span aria-hidden="true" data-state={checked ? 'checked' : 'unchecked'} className={cn(
      'inline-flex h-6 w-11 shrink-0 items-center rounded-full border-2 border-transparent transition-colors duration-150 motion-reduce:transition-none',
      checked ? 'bg-primary' : 'bg-input', className
    )}>
      <span className={cn('block size-5 rounded-full bg-background transition-transform duration-150 motion-reduce:transition-none', checked ? 'translate-x-5' : 'translate-x-0')} />
    </span>
  )
}

export function SettingsSwitch({ className, ...props }: Readonly<SwitchProps>) {
  return <Switch className={cn('relative before:absolute before:-inset-x-1 before:-inset-y-2.5 [&>span]:shadow-none motion-reduce:transition-none motion-reduce:[&>span]:transition-none', className)} {...props} />
}
