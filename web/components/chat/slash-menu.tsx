'use client'

import * as React from 'react'
import { Sparkles, FileText, Eraser, Settings2, Database, History } from 'lucide-react'

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

const COMMANDS = [
  {
    id: 'knowledge',
    label: '打开知识库',
    description: '跳转到知识库页面，查看文档与索引状态',
    keywords: ['knowledge', 'kb', 'docs', '文档', '知识库'],
    icon: Database,
  },
  {
    id: 'history',
    label: '打开历史会话',
    description: '前往历史会话页，回看旧问答与上下文',
    keywords: ['history', '会话', '记录', 'trace'],
    icon: History,
  },
  {
    id: 'prompt',
    label: '插入提示模板',
    description: '快速填入一条适合知识库摘要的提示',
    keywords: ['prompt', '模板', 'summary', '摘要'],
    icon: Sparkles,
  },
  {
    id: 'cite_analysis',
    label: '引用核查 + 差异分析',
    description: '预填一条强约束提示，要求结论、证据与差异并列输出',
    keywords: ['citation', 'analysis', 'evidence', '引用', '分析'],
    icon: FileText,
  },
  {
    id: 'config',
    label: '打开 RAG 配置',
    description: '调整检索模式、Top K 与过滤条件',
    keywords: ['config', 'settings', '检索', '参数'],
    icon: Settings2,
  },
  {
    id: 'clear',
    label: '清空当前输入',
    description: '只清理输入框，不影响已有会话记录',
    keywords: ['clear', 'erase', '清空'],
    icon: Eraser,
  },
] as const

export function SlashMenu({ open, onOpenChange, onSelect, position }: Readonly<SlashMenuProps>) {
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
          <CommandInput placeholder="搜索命令或用途..." autoFocus />
          <CommandList>
            <CommandEmpty>未找到匹配命令</CommandEmpty>
            <CommandGroup heading="快捷指令">
              {COMMANDS.map((cmd) => (
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
