'use client'

import { PopoverAnchor } from '@radix-ui/react-popover'
import * as React from 'react'
import { useTranslations } from 'next-intl'

import { Sparkles, FileText, Eraser, Settings2, Database, History } from '@/components/icons'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command'
import { Popover, PopoverContent } from '@/components/ui/popover'

const COMMANDS = [
  { id: 'knowledge', icon: Database },
  { id: 'history', icon: History },
  { id: 'prompt', icon: Sparkles },
  { id: 'cite_analysis', icon: FileText },
  { id: 'config', icon: Settings2 },
  { id: 'clear', icon: Eraser },
] as const

type SlashCommandId = (typeof COMMANDS)[number]['id']

type SlashMenuProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (command: SlashCommandId) => void
  position: { top: number; left: number }
}

export function SlashMenu({ open, onOpenChange, onSelect, position }: Readonly<SlashMenuProps>) {
  const t = useTranslations('SlashMenu')
  const heading = t('heading')
  const returnFocusRef = React.useRef<HTMLTextAreaElement>(null)

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverAnchor
        style={{ position: 'fixed', top: position.top, left: position.left, width: 1, height: 1 }}
        aria-hidden="true"
      />
      <PopoverContent
        className="w-80 overflow-hidden border border-border/70 bg-popover/95 p-0 shadow-strong backdrop-blur"
        align="start"
        side="top"
        aria-label={heading}
        onOpenAutoFocus={() => {
          const focusedElement = document.activeElement
          returnFocusRef.current = focusedElement instanceof HTMLTextAreaElement ? focusedElement : null
        }}
        onInteractOutside={() => {
          returnFocusRef.current = null
        }}
        onCloseAutoFocus={(event) => {
          const opener = returnFocusRef.current
          returnFocusRef.current = null
          if (opener?.isConnected && document.activeElement === document.body) {
            event.preventDefault()
            opener.focus({ preventScroll: true })
          }
        }}
      >
        <Command loop label={heading}>
          <CommandInput placeholder={t('placeholder')} />
          <CommandList>
            <CommandEmpty>{t('empty')}</CommandEmpty>
            <CommandGroup heading={heading}>
              {COMMANDS.map(({ id, icon: Icon }) => {
                const label = t(`commands.${id}.label`)
                const description = t(`commands.${id}.description`)
                const keywords = t.raw(`commands.${id}.keywords`) as string[]
                return (
                  <CommandItem
                    key={id}
                    value={id}
                    keywords={[label, description, ...keywords]}
                    onSelect={() => {
                      returnFocusRef.current = null
                      onSelect(id)
                    }}
                    className="items-start gap-3 rounded-xl px-3 py-3"
                  >
                    <div className="mt-0.5 flex size-8 items-center justify-center rounded-xl border border-primary/15 bg-primary/10 text-primary">
                      <Icon className="size-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-foreground">{label}</div>
                      <div className="mt-1 text-xs leading-5 text-muted-foreground">{description}</div>
                    </div>
                    <CommandShortcut>↵</CommandShortcut>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
