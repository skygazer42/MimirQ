// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { expectSourceToContain } from '@/lib/source-test-utils'

describe('history route source', () => {
  it('keeps the server wrapper auth-agnostic and lets the client fetch authenticated history data', () => {
    const page = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(page).not.toContain("'use client'")
    expect(page).toContain("import HistoryPageClient from './page-client'")
    expect(page).toContain('export default function HistoryPage')
    expect(page).toContain('<HistoryPageClient />')
    expect(page).not.toContain('getServerHistoryPageData')
    expect(page).not.toContain('initialConversationsLoaded={false}')

    expect(client).toContain("'use client'")
    expect(client).toContain("searchParams.get('id')")
    expect(client).toContain("import { skipToken, useInfiniteQuery, useQueryClient } from '@tanstack/react-query'")
    expect(client).toContain('queryKey: queryKeys.chat.conversationPages(conversationListParams)')
    expect(client).toContain('...(conversationSearchTerm ? { q: conversationSearchTerm } : {})')
    expect(client).toContain('maxLength={500}')
    expect(client).toContain('getNextPageParam: (lastPage) => lastPage.next_skip')
    expect(client).toContain('data-history-sidebar-scroll')
    expect(client).toContain('conversationLoadMoreRef')
    expect(client).toContain('globalThis.window.setInterval')
  })

  it('suppresses hydration drift for relative activity timestamps in the sidebar list', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('<time')
    expect(client).toContain('suppressHydrationWarning')
    expect(client).toContain('dateTime={conversation.last_message_at ?? conversation.updated_at}')
    expect(client).toContain(
      "formatRelativeTime(conversation.last_message_at ?? conversation.updated_at, locale, t('justNow'))",
    )
  })

  it('suppresses hydration drift for message-group date labels in the active conversation pane', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expectSourceToContain(client, '<div suppressHydrationWarning')
    expect(client).toContain('{group.label}')
  })

  it('suppresses hydration drift for selected-conversation created-at chips', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('<span suppressHydrationWarning')
    expect(client).toContain('{formatDate(selectedConversation.created_at, locale)}')
  })

  it('suppresses hydration drift for sidebar conversation-group labels', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('<span suppressHydrationWarning>{group}</span>')
  })

  it('reads message pages in the client before showing grouped history', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('if (messagesQuery.data === undefined) return null')
    expect(client).toContain('groupedMessages.map(')
  })

  it('keeps the history workspace on a flat ruled boundary system', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('data-history-shell="ruled"')
    expect(client).toContain('data-history-sidebar="true"')
    expect(client).toContain('data-history-detail-header="true"')
    expect(client).toContain('@min-[44rem]:border-r')
    expect(client).not.toContain('rounded-lg border border-foreground/15 bg-background')
    expect(client).not.toContain('backdrop-blur')
    expect(client).not.toContain('rounded-3xl')
    expect(client).not.toContain('shadow-soft')
  })
})
