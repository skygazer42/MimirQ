import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('command menu remote search', () => {
  it('passes the debounced query through dataset and conversation query keys and requests', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(source).toContain('const COMMAND_MENU_SEARCH_MAX_LENGTH = 200')
    expect(source).toContain('query.trim().slice(0, COMMAND_MENU_SEARCH_MAX_LENGTH)')
    expect(source).toContain('maxLength={COMMAND_MENU_SEARCH_MAX_LENGTH}')
    expect(source).toContain('const datasetSearchParams = React.useMemo')
    expect(source).toContain('const conversationSearchParams = React.useMemo')
    expect(source).toContain('q: debouncedSearchQuery')
    expect(source).toContain('queryKeys.datasets.list(datasetSearchParams)')
    expect(source).toContain('datasetApi.list(datasetSearchParams)')
    expect(source).toContain('queryKeys.chat.conversations(conversationSearchParams)')
    expect(source).toContain('chatApi.listConversations(conversationSearchParams)')
  })

  it('keeps the Chinese-first command surface and semantic workflow icons', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')
    const commandUi = fs.readFileSync(path.resolve(__dirname, 'ui/command.tsx'), 'utf8')
    const messages = fs.readFileSync(path.resolve(__dirname, '../i18n/messages/zh-CN/command.ts'), 'utf8')

    expect(source).toContain('const Icon = command.icon')
    expect(source).toContain('command.key.toUpperCase()')
    expect(messages).toContain("title: '命令中心'")
    expect(messages).toContain("keyboardWorkflow: '快捷工作流'")
    expect(messages).toContain("label: '打开文档工作台'")
    expect(messages).not.toContain('Command Center')
    expect(messages).not.toContain('Go to Documents')
    expect(commandUi).toContain('data-[disabled=true]:opacity-50')
    expect(commandUi).not.toContain('data-[disabled]:opacity-50')
  })

  it('keeps the command surfaces on ruled neutral boundaries', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')
    const commandUi = fs.readFileSync(path.resolve(__dirname, 'ui/command.tsx'), 'utf8')

    expect(commandUi).toContain('data-command-dialog="true"')
    expect(commandUi).toContain('border border-foreground/15 bg-background p-0 shadow-none')
    expect(commandUi).toContain('border-b border-foreground/10')
    expect(commandUi).toContain('aria-selected:bg-foreground/10 aria-selected:text-foreground')
    expect(commandUi).not.toContain('shadow-strong')
    expect(commandUi).not.toContain('aria-selected:text-primary')

    expect(source).toContain('data-command-menu-header="true"')
    expect(source).toContain('data-command-workflow-group="true"')
    expect(source).toContain('border-b border-foreground/10 bg-background')
    expect(source).toContain('border border-foreground/10 bg-background text-foreground')
    expect(source).not.toContain('aria-selected:bg-info/8')
  })
})
