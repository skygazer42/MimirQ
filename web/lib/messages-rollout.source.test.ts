import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('messages catalog rollout source guards', () => {
  it('keeps common chat workspace labels sourced from the messages catalog', () => {
    const chatArea = read('components/chat-area.tsx')

    expect(chatArea).toContain("import { messages as uiMessages } from '@/lib/messages'")
    expect(chatArea).toContain('uiMessages.chat.showEarlierMessages')
    expect(chatArea).toContain('uiMessages.chat.jumpToLatest')
    expect(chatArea).toContain('uiMessages.chat.conversationTools')
    expect(chatArea).toContain('uiMessages.chat.defaultTemplate')

    expect(chatArea).not.toContain('显示更早消息（')
    expect(chatArea).not.toContain('回到最新')
    expect(chatArea).not.toContain('对话工具')
    expect(chatArea).not.toContain('默认模板')
  })

  it('keeps history page shell text sourced from the messages catalog', () => {
    const historyPage = read('app/history/page-client.tsx')

    expect(historyPage).toContain("import { messages as uiMessages } from '@/lib/messages'")
    expect(historyPage).toContain('uiMessages.history.loadingPage')
    expect(historyPage).toContain('uiMessages.history.pageTitle')
    expect(historyPage).toContain('uiMessages.history.newConversation')
    expect(historyPage).toContain('uiMessages.history.searchPlaceholder')

    expect(historyPage).not.toContain('正在加载历史记录...')
    expect(historyPage).not.toContain('问答历史')
    expect(historyPage).not.toContain('新建对话')
    expect(historyPage).not.toContain('搜索对话...')
  })
})
