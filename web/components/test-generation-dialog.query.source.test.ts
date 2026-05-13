import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('test generation dialog query convergence', () => {
  it('uses TanStack Query for documents, datasets, and conversations source lists', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'test-generation-dialog.tsx'),
      'utf8'
    )

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain('queryKey: queryKeys.documents.list(TEST_GEN_DOCUMENT_PARAMS)')
    expect(src).toContain('queryKey: queryKeys.datasets.list(TEST_GEN_DATASET_PARAMS)')
    expect(src).toContain('queryKey: queryKeys.chat.conversations(TEST_GEN_CONVERSATION_PARAMS)')
    expect(src).not.toContain('const loadData = async () => {')
    expect(src).not.toContain('setDocuments(docsResult.items)')
    expect(src).not.toContain('setDatasets(datasetsResult.items)')
    expect(src).not.toContain('setConversations(convsResult.items || [])')
  })
})
