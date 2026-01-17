"use client"

import * as React from "react"
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
  CommandInput
} from "@/components/ui/command"
import { 
  Popover, 
  PopoverContent, 
  PopoverTrigger 
} from "@/components/ui/popover"
import { Sparkles, FileText, Eraser, Settings2 } from "lucide-react"

interface SlashMenuProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (command: string) => void
  position: { top: number; left: number }
}

const COMMANDS = [
  { id: "prompt", label: "插入提示词", icon: Sparkles },
  { id: "doc", label: "引用文档", icon: FileText },
  { id: "clear", label: "清空对话", icon: Eraser },
  { id: "config", label: "调整参数", icon: Settings2 },
]

export function SlashMenu({ open, onOpenChange, onSelect, position }: SlashMenuProps) {
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <div 
            style={{ 
                position: 'fixed', 
                top: position.top, 
                left: position.left, 
                width: 1, 
                height: 1 
            }} 
        />
      </PopoverTrigger>
      <PopoverContent className="p-0 w-64" align="start" side="top">
        <Command>
          <CommandInput placeholder="输入命令..." autoFocus />
          <CommandList>
            <CommandGroup heading="快捷指令">
              {COMMANDS.map((cmd) => (
                <CommandItem key={cmd.id} onSelect={() => onSelect(cmd.id)}>
                  <cmd.icon className="mr-2 h-4 w-4" />
                  <span>{cmd.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
