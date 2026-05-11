import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chat area autorun source', () => {
  it('can auto-send prompt handoffs from command menu routes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('initialAutoSendPrompt')
    expect(src).toContain('autoSendPromptRef')
    expect(src).toContain('submitMessage(p)')
  })

  it('loads chat shell metadata through TanStack Query instead of effect-owned request state', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain("import { queryKeys } from '@/lib/query-keys'")
    expect(src).toContain('queryKey: queryKeys.settings.snapshot')
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).toContain('queryKey: queryKeys.documents.list')
    expect(src).toContain('queryKey: queryKeys.prompts.list')
    expect(src).not.toContain('loadWelcomeStats')
    expect(src).not.toContain('loadTemplates')
    expect(src).not.toContain('setDatasets(')
    expect(src).not.toContain('setPromptTemplates(')
  })

  it('submits document-selection and follow-up actions to the backend instead of only prefilling', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')
    const messageSrc = fs.readFileSync(path.resolve(__dirname, 'chat/message-item.tsx'), 'utf8')
    const floatingMenuSrc = fs.readFileSync(path.resolve(__dirname, 'document-viewer/floating-menu.tsx'), 'utf8')

    expect(src).toContain("globalEventBus.on('chat:submit'")
    expect(src).toContain('if (submitMessage(prompt)) {')
    expect(src).toContain("globalEventBus.on('chat:send'")
    expect(messageSrc).toContain("globalEventBus.emit('chat:submit', prompt)")
    expect(floatingMenuSrc).toContain('globalEventBus.emit("chat:submit", prompt)')
  })

  it('scopes chat requests to the currently opened document when the viewer is active', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain("useDocumentView((state) => state.documentId)")
    expect(src).toContain('documentIds: activeDocumentIds')
  })

  it('keeps first-page chat on a low-latency RAG profile by default', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('enable_multi_query: false')
    expect(src).toContain('enable_hyde: false')
  })

  it('exposes current conversation RAG trace without leaving the chat page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain("import { RagTraceDialog } from '@/components/rag-trace/rag-trace-dialog'")
    expect(src).toContain('const [traceDialogOpen, setTraceDialogOpen] = useState(false)')
    expect(src).toContain("title={conversationId ? t('viewRagTrace') : t('sendMessageFirst')}")
    expect(src).toContain('<RagTraceDialog')
    expect(src).toContain('conversationId={conversationId ?? null}')
  })
})
