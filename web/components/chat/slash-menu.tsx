'use client'

import * as React from 'react'
import { Sparkles, FileText, Eraser, Settings2, Database, History } from 'lucide-react'
import { useTranslations } from 'next-intl'

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'

interface SlashMenuProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (command: string) => void
  position: { top: number; left: number }
}

type SlashCommandId = 'knowledge' | 'history' | 'prompt' | 'cite_analysis' | 'config' | 'clear'

const COMMAND_ICONS: Record<SlashCommandId, React.ComponentType<{ className?: string }>> = {
  knowledge: Database,
  history: History,
  prompt: Sparkles,
  cite_analysis: FileText,
  config: Settings2,
  clear: Eraser,
}

export function SlashMenu({ open, onOpenChange, onSelect, position }: Readonly<SlashMenuProps>) {
  const t = useTranslations('SlashMenu')
  const commands = React.useMemo(
    () =>
      (Object.keys(COMMAND_ICONS) as SlashCommandId[]).map((id) => ({
        id,
        icon: COMMAND_ICONS[id],
        label: t(`commands.${id}.label`),
        description: t(`commands.${id}.description`),
        keywords: t.raw(`commands.${id}.keywords`) as string[],
      })),
    [t]
  )

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <div
          style={{
            position: 'fixed',
            top: position.top,
            left: position.left,
            width: 1,
            height: 1,
          }}
        />
      </PopoverTrigger>
      <PopoverContent
        className="w-80 overflow-hidden border border-border/70 bg-popover/95 p-0 shadow-strong backdrop-blur"
        align="start"
        side="top"
      >
        <Command loop>
          <CommandInput placeholder={t('placeholder')} autoFocus />
          <CommandList>
            <CommandEmpty>{t('empty')}</CommandEmpty>
            <CommandGroup heading={t('heading')}>
              {commands.map((cmd) => (
                <CommandItem
                  key={cmd.id}
                  value={`${cmd.id} ${cmd.label} ${cmd.description} ${cmd.keywords.join(' ')}`}
                  keywords={[...cmd.keywords]}
                  onSelect={() => onSelect(cmd.id)}
                  className="items-start gap-3 rounded-xl px-3 py-3"
                >
                  <div className="mt-0.5 flex size-8 items-center justify-center rounded-xl border border-primary/15 bg-primary/10 text-primary">
                    <cmd.icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-foreground">{cmd.label}</div>
                    <div className="mt-1 text-xs leading-5 text-muted-foreground">{cmd.description}</div>
                  </div>
                  <CommandShortcut>↵</CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
