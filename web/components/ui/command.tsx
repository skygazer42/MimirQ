'use client'

import * as React from 'react'
import { type DialogProps } from '@radix-ui/react-dialog'
import { Command as CommandPrimitive } from 'cmdk'
import { Search } from '@/components/icons'
import { useTranslations } from 'next-intl'

import { cn } from '@/lib/utils'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import type { RadixRef } from '@/lib/radix-utils'
import styles from './command.module.css'

const Command = React.forwardRef<
  RadixRef<typeof CommandPrimitive>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => (
  <CommandPrimitive
    ref={ref}
    className={cn('flex h-full w-full flex-col overflow-hidden rounded-md bg-background text-foreground', className)}
    {...props}
  />
))
Command.displayName = CommandPrimitive.displayName

type CommandDialogProps = DialogProps & { shouldFilter?: boolean; id?: string }

export function CommandDialog({ children, shouldFilter, id, ...props }: CommandDialogProps) {
  const t = useTranslations('CommonUi')
  const returnFocusRef = React.useRef<HTMLElement | null>(null)

  return (
    <Dialog {...props}>
      <DialogContent
        id={id}
        showCloseButton={false}
        data-command-dialog="true"
        className={cn(
          styles.dialog,
          'left-1/2 top-[18dvh] translate-y-0 flex max-h-[calc(82dvh-1rem)] w-[calc(100%-2rem)] flex-col gap-0 overflow-hidden rounded-xl border border-foreground/15 bg-background p-0 shadow-strong data-[state=open]:animate-none data-[state=closed]:animate-none sm:max-w-[600px]',
        )}
        onOpenAutoFocus={(event) => {
          const content = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
          const opener = document.activeElement
          if (opener instanceof HTMLElement && opener !== document.body && !content?.contains(opener)) {
            returnFocusRef.current = opener
          }
          const input = content?.querySelector<HTMLInputElement>('[cmdk-input]')
          if (input) {
            event.preventDefault()
            input.focus()
          }
        }}
        onCloseAutoFocus={(event) => {
          // The command menu opens from several controls, without a DialogTrigger.
          const opener = returnFocusRef.current
          returnFocusRef.current = null
          const content = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
          const focused = document.activeElement
          // A command may already have opened and focused another panel.
          if (
            focused instanceof HTMLElement &&
            focused !== document.body &&
            focused !== opener &&
            !content?.contains(focused)
          ) {
            event.preventDefault()
            return
          }
          const target =
            opener?.isConnected && !opener.matches(':disabled') && opener.closest('[inert]') === null
              ? opener
              : document.getElementById('main-content')
          if (target !== null && target.closest('[inert]') === null) {
            event.preventDefault()
            target.focus({ preventScroll: true })
          }
        }}
      >
        <DialogTitle className="sr-only">{t('command.title')}</DialogTitle>
        <DialogDescription className="sr-only">{t('command.description')}</DialogDescription>
        <Command
          shouldFilter={shouldFilter}
          className="h-auto min-h-0 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group]]:px-0 [&_[data-cmdk-input-wrapper]]:shrink-0 [&_[data-cmdk-input-wrapper]]:px-4 [&_[cmdk-item]]:min-h-10 [&_[cmdk-item]]:cursor-pointer [&_[cmdk-item]]:items-center [&_[cmdk-item]]:gap-2.5 [&_[cmdk-item]]:rounded-lg [&_[cmdk-item]]:px-3 [&_[cmdk-item]]:py-2 [&_[cmdk-item]]:text-sm [&_[cmdk-item]]:leading-5 [&_[cmdk-item]_svg]:mr-0 [&_[cmdk-item]_svg]:shrink-0 [&_[cmdk-item]_svg]:text-muted-foreground"
        >
          {children}
        </Command>
      </DialogContent>
    </Dialog>
  )
}

const CommandInput = React.forwardRef<
  RadixRef<typeof CommandPrimitive.Input>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div
    className="flex items-center border-b border-foreground/10 px-4 [&:has(input:focus)_svg]:text-foreground"
    data-cmdk-input-wrapper=""
  >
    <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground transition-colors" aria-hidden="true" />
    <CommandPrimitive.Input
      ref={ref}
      className={cn(
        'flex h-11 w-full rounded-md bg-transparent py-3 text-sm text-foreground outline-none placeholder:text-muted-foreground/70 disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  </div>
))

CommandInput.displayName = CommandPrimitive.Input.displayName

const CommandList = React.forwardRef<
  RadixRef<typeof CommandPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.List
    ref={ref}
    className={cn(
      'max-h-[min(420px,62dvh)] overflow-y-auto overscroll-contain no-scrollbar overflow-x-hidden transition-[max-height] duration-200 ease-out',
      className,
    )}
    {...props}
  />
))

CommandList.displayName = CommandPrimitive.List.displayName

const CommandEmpty = React.forwardRef<
  RadixRef<typeof CommandPrimitive.Empty>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Empty ref={ref} className={cn('py-6 text-center text-sm', className)} {...props} />
))

CommandEmpty.displayName = CommandPrimitive.Empty.displayName

const CommandGroup = React.forwardRef<
  RadixRef<typeof CommandPrimitive.Group>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Group
    ref={ref}
    className={cn(
      'overflow-hidden p-1 text-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground',
      className,
    )}
    {...props}
  />
))

CommandGroup.displayName = CommandPrimitive.Group.displayName

const CommandSeparator = React.forwardRef<
  RadixRef<typeof CommandPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Separator ref={ref} className={cn('-mx-1 h-px bg-foreground/10', className)} {...props} />
))
CommandSeparator.displayName = CommandPrimitive.Separator.displayName

const CommandItem = React.forwardRef<
  RadixRef<typeof CommandPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Item
    ref={ref}
    className={cn(
      'relative flex cursor-default select-none items-center rounded-md px-2 py-1.5 text-sm outline-none aria-selected:bg-foreground/10 aria-selected:text-foreground aria-selected:before:absolute aria-selected:before:bottom-1 aria-selected:before:left-0 aria-selected:before:top-1 aria-selected:before:w-px aria-selected:before:bg-foreground/30 data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50 transition-colors duration-200',
      className,
    )}
    {...props}
  />
))

CommandItem.displayName = CommandPrimitive.Item.displayName

export function CommandShortcut({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        'ml-auto inline-flex min-h-5 items-center rounded-md border border-foreground/10 bg-background px-1.5 font-mono text-[10px] font-semibold text-muted-foreground',
        className,
      )}
      {...props}
    />
  )
}
CommandShortcut.displayName = 'CommandShortcut'

export { Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem, CommandSeparator }
