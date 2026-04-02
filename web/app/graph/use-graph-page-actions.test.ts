import { describe, expect, it, vi } from 'vitest'

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

import { buildGraphNodeChatPrompt } from './use-graph-page-actions'

describe('buildGraphNodeChatPrompt', () => {
  it('prefills a document-summary prompt when the node is tied to a source document', () => {
    const prompt = buildGraphNodeChatPrompt({
      id: 'node-1',
      label: '季度经营复盘',
      source: 'doc-42',
      meta: {
        kind: 'entity',
        document_id: 'doc-42',
      },
    } as any)

    expect(prompt).toContain('总结一下该文档的核心观点')
    expect(prompt).toContain('季度经营复盘')
    expect(prompt).toContain('doc-42')
  })

  it('falls back to a graph-centric analysis prompt for entity nodes without document ids', () => {
    const prompt = buildGraphNodeChatPrompt({
      id: 'node-2',
      label: '供应链网络',
      meta: {
        kind: 'entity',
      },
    } as any)

    expect(prompt).toContain('图谱节点')
    expect(prompt).toContain('供应链网络')
    expect(prompt).toContain('关联事件')
  })
})
