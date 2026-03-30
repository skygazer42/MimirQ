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
    expect(client).toContain('useState<Conversation[]>(initialConversations)')
    expect(client).toContain('useState<Message[]>(initialMessages)')
  })
})
