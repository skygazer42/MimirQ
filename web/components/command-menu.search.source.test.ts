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
})
