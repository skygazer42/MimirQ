// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'
import ts from 'typescript'

describe('history route source', () => {
  it('keeps the server wrapper auth-agnostic and lets the client fetch authenticated history data', () => {
    const page = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(page).not.toContain("'use client'")
    expect(page).toContain("import HistoryPageClient from './page-client'")
    expect(page).toContain('export default async function HistoryPage')
    expect(page).toContain('<HistoryPageClient initialConversationId={sp?.id || null} />')
    expect(page).not.toContain('getServerHistoryPageData')
    expect(page).not.toContain('initialConversationsLoaded={false}')

    expect(client).toContain("'use client'")
    expect(client).toContain('initialConversations')
    expect(client).toContain('initialMessages')
    expect(client).toContain('initialConversationId')
    expect(client).toContain("import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'")
    expect(client).toContain('queryKey: queryKeys.chat.conversationPages(conversationListParams)')
    expect(client).toContain('...(conversationSearchTerm ? { q: conversationSearchTerm } : {})')
    expect(client).toContain('maxLength={500}')
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
    expect(client).toContain(
      'dateTime={conversation.last_message_at || conversation.updated_at || conversation.created_at}',
    )
    expect(client).toContain(
      "formatRelativeTime(conversation.last_message_at || conversation.updated_at, locale, t('justNow'))",
    )
  })

  it('suppresses hydration drift for message-group date labels in the active conversation pane', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')
    const source = ts.createSourceFile('page-client.tsx', client, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const dateLabels: { tag: string; expression: string; suppressHydrationWarning: boolean }[] = []
    function visit(node: ts.Node) {
      if (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'div') {
        for (const child of node.children) {
          if (!ts.isJsxExpression(child) || !child.expression) continue
          dateLabels.push({
            tag: 'div',
            expression: child.expression.getText(source),
            suppressHydrationWarning: node.openingElement.attributes.properties.some(
              (attribute) =>
                ts.isJsxAttribute(attribute) &&
                attribute.name.getText(source) === 'suppressHydrationWarning' &&
                (!attribute.initializer ||
                  (ts.isJsxExpression(attribute.initializer) &&
                    attribute.initializer.expression?.kind === ts.SyntaxKind.TrueKeyword)),
            ),
          })
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(source)

    expect(dateLabels).toContainEqual({ tag: 'div', expression: 'group.label', suppressHydrationWarning: true })
  })

  it('suppresses hydration drift for selected-conversation created-at chips', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('<span suppressHydrationWarning')
    expect(client).toContain('{formatDate(displayConversation.created_at, locale)}')
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

  it('keeps the history workspace on a flat ruled boundary system', () => {
    const client = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(client).toContain('data-history-shell="ruled"')
    expect(client).toContain('data-history-sidebar="true"')
    expect(client).toContain('data-history-detail-header="true"')
    expect(client).toContain('border-r border-foreground/15 bg-background')
    expect(client).toContain('border-b border-foreground/15 bg-background')
    expect(client).toContain('rounded-md border border-foreground/10 bg-background')
    expect(client).not.toContain('backdrop-blur')
    expect(client).not.toContain('rounded-3xl')
    expect(client).not.toContain('shadow-soft')
  })
})
