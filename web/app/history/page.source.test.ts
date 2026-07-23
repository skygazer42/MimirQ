// Source contract check only; this is not behavior coverage.
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
    expect(client).toContain("import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'")
    expect(client).toContain('queryKey: queryKeys.chat.conversationPages({ limit: CONVERSATION_PAGE_SIZE })')
    expect(client).toContain('getNextPageParam: (lastPage, allPages) =>')
    expect(client).toContain('data-history-sidebar-scroll')
    expect(client).toContain('conversationLoadMoreRef')
    expect(client).toContain('globalThis.window.setInterval')
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

  it('suppresses hydration drift for message-group date labels in the active conversation pane', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('<div suppressHydrationWarning className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground/28 whitespace-nowrap">')
    expect(client).toContain('{group.label}')
  })

  it('suppresses hydration drift for selected-conversation created-at chips', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('<span suppressHydrationWarning className="inline-flex items-center gap-1 rounded-md bg-muted/30 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground/50 border border-border/10">')
    expect(client).toContain('{formatDate(selectedConversation.created_at, locale)}')
  })

  it('suppresses hydration drift for sidebar conversation-group labels', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('<span suppressHydrationWarning>{group}</span>')
  })

  it('uses UTC day bucketing for sidebar and message grouping to avoid timezone-driven hydration drift', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('getUTCFullYear')
    expect(client).toContain('getUTCMonth')
    expect(client).toContain('getUTCDate')
  })
})
