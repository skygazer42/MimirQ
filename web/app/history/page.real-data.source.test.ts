import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page real-data contract', () => {
  it('does not expose local-only starred conversation controls on the non-demo history page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain("historyView, setHistoryView] = useState<'all' | 'recent' | 'starred'>")
    expect(src).not.toContain('starredConversationIds')
    expect(src).not.toContain('toggleStarConversation')
    expect(src).not.toContain("['starred', '收藏']")
    expect(src).not.toContain("label={isStarred ? '取消收藏' : '收藏对话'}")
    expect(src).not.toContain('<Star className=')
  })

  it('loads the conversation list through TanStack Query instead of a local loadConversations helper', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'")
    expect(src).toContain('queryKey: queryKeys.chat.conversations({ limit: 100 })')
    expect(src).not.toContain('const loadConversations = useCallback(async () => {')
    expect(src).not.toContain('setConversations(result.items || [])')
    expect(src).toContain('queryClient.setQueryData(')
  })
})
