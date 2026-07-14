// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('server history page data source', () => {
  it('fetches conversation lists and initial message pages on the server with no-store semantics', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'server-history-page-data.ts'), 'utf8')

    expect(src).toContain("import 'server-only'")
    expect(src).toContain("import { getServerAuthHeaders } from '@/lib/server-auth-headers'")
    expect(src).toContain('/chat/conversations?skip=0&limit=100')
    expect(src).toContain('initialHasMoreConversations')
    expect(src).toContain('initialConversationNextSkip')
    expect(src).toContain('/messages?limit=')
    expect(src).toContain("cache: 'no-store'")
    expect(src).toContain('export async function getServerHistoryPageData(')
  })
})
