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

    expect(chatArea).toContain("import { useTranslations } from 'next-intl'")
    expect(chatArea).toContain("const t = useTranslations('Chat')")
    expect(chatArea).toContain("t('showEarlierMessages')")
    expect(chatArea).toContain("t('jumpToLatest')")
    expect(chatArea).toContain("t('conversationTools')")
    expect(chatArea).toContain("t('defaultTemplate')")

    expect(chatArea).not.toContain("import { messages as uiMessages } from '@/lib/messages'")
    expect(chatArea).not.toContain('uiMessages.chat.')
  })

  it('keeps history page shell text sourced from the messages catalog', () => {
    const historyPage = read('app/history/page-client.tsx')

    expect(historyPage).toContain("import { useLocale, useTranslations } from 'next-intl'")
    expect(historyPage).toContain("const t = useTranslations('History')")
    expect(historyPage).toContain("const locale = useLocale()")
    expect(historyPage).toContain("t('loadingPage')")
    expect(historyPage).toContain("t('pageTitle')")
    expect(historyPage).toContain("t('startNewConversation')")
    expect(historyPage).toContain("t('searchPlaceholder')")

    expect(historyPage).not.toContain("import { messages as uiMessages } from '@/lib/messages'")
    expect(historyPage).not.toContain('uiMessages.history.')
  })
})
