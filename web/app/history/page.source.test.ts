import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history route source', () => {
  it('uses a server wrapper to prefetch the initial history payload before hydrating the client shell', () => {
    const page = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(page).not.toContain("'use client'")
    expect(page).toContain("import HistoryPageClient from './page-client'")
    expect(page).toContain("import { getServerHistoryPageData } from '@/lib/server-history-page-data'")
    expect(page).toContain('export default async function HistoryPage')
    expect(page).toContain('const initialData = await getServerHistoryPageData(')
    expect(page).toContain('<HistoryPageClient {...initialData} />')

    expect(client).toContain("'use client'")
    expect(client).toContain('initialConversations')
    expect(client).toContain('initialMessages')
    expect(client).toContain('initialConversationId')
    expect(client).toContain("import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'")
    expect(client).toContain('queryKey: queryKeys.chat.conversations({ limit: 100 })')
    expect(client).toContain("queryKey: queryKeys.chat.messages(selectedConversationId || '')")
    expect(client).not.toContain('useState<Conversation[]>(initialConversations)')
    expect(client).not.toContain('useState<Message[]>(initialMessages)')
    expect(client).toContain('initialMessages')
  })

  it('suppresses hydration drift for relative activity timestamps in the sidebar list', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('<time')
    expect(client).toContain('suppressHydrationWarning')
    expect(client).toContain('dateTime={conversation.last_message_at || conversation.updated_at || conversation.created_at}')
    expect(client).toContain("formatRelativeTime(conversation.last_message_at || conversation.updated_at, locale, t('justNow'))")
  })
})
